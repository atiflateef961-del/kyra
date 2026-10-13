from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
try:
    BACKEND_PORT = int(os.getenv("APP_PORT", "8000"))
except ValueError as cause:
    raise SystemExit("APP_PORT in the environment must be an integer.") from cause
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
FRONTEND_PORT = 5173


@dataclass(frozen=True)
class PortOwner:
    pid: int
    name: str
    kind: str
    parent_pid: int = 0
    executable_path: str | None = None
    command_line: str | None = None
    working_directory: str | None = None


class PortState(str, Enum):
    FREE = "FREE"
    HEALTHY_KYRA = "HEALTHY_KYRA"
    STALE_KYRA = "STALE_KYRA"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"


@dataclass(frozen=True)
class BackendProbe:
    protocol: str
    is_kyra: bool
    cors_allowed: bool
    detail: str


@dataclass(frozen=True)
class FrontendProbe:
    protocol: str
    is_kyra: bool
    mode: str | None
    agent_url: str | None
    detail: str


def current_lan_ip() -> str:
    """Ask Windows routing which local interface it would use for LAN traffic."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 80))
        address = probe.getsockname()[0]
    if address.startswith("127."):
        raise RuntimeError("No active LAN IPv4 address was found for this computer.")
    return address


def classify_process(name: str, command_line: str, working_directory: str) -> str | None:
    """Identify only this checkout's supported backend and Vite processes."""
    process_name = name.casefold()
    command = command_line.casefold()
    try:
        cwd = Path(working_directory).resolve()
    except (OSError, RuntimeError):
        return None

    if process_name in {"python.exe", "python"}:
        root_launcher = cwd == ROOT and "backend.app.main:app" in command
        backend_directory = cwd == ROOT / "backend" and "app.main:app" in command
        if "uvicorn" in command and (root_launcher or backend_directory):
            return "backend"
    if process_name in {"node.exe", "node"} and cwd == ROOT / "frontend":
        if "vite" in command:
            return "frontend"
    return None


def process_command_and_cwd(pid: int) -> tuple[str, str, int] | None:
    """Read same-user Windows process metadata without printing command-line data."""
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        return None

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.ReadProcessMemory.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    )
    kernel.ReadProcessMemory.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll.NtQueryInformationProcess.argtypes = (
        wintypes.HANDLE,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    )
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG

    handle = kernel.OpenProcess(0x0410, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    if not handle:
        return None

    def read_memory(address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        succeeded = kernel.ReadProcessMemory(
            handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(bytes_read),
        )
        if not succeeded or bytes_read.value != size:
            raise OSError(ctypes.get_last_error(), "Could not read process metadata safely.")
        return buffer.raw

    def unicode_string(address: int) -> str:
        header = read_memory(address, 16)
        length = int.from_bytes(header[:2], "little")
        buffer_address = int.from_bytes(header[8:16], "little")
        if length > 32766 or (length and not buffer_address):
            raise ValueError("Process metadata has an invalid string length.")
        return read_memory(buffer_address, length).decode("utf-16-le") if length else ""

    try:
        basic_info = ctypes.create_string_buffer(48)
        returned = wintypes.ULONG()
        status = ntdll.NtQueryInformationProcess(
            handle, 0, basic_info, len(basic_info), ctypes.byref(returned),
        )
        if status < 0:
            return None
        peb_address = int.from_bytes(basic_info.raw[8:16], "little")
        parent_pid = int.from_bytes(basic_info.raw[40:48], "little")
        process_parameters = int.from_bytes(read_memory(peb_address + 0x20, 8), "little")
        cwd = unicode_string(process_parameters + 0x38)
        command_line = unicode_string(process_parameters + 0x70)
        return command_line, cwd, parent_pid
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        kernel.CloseHandle(handle)


def process_using_port(port: int) -> PortOwner | None:
    if os.name != "nt":
        with socket.socket() as probe:
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                return PortOwner(0, "unknown process", "unknown")
        return None

    result = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
            continue
        if fields[1].rsplit(":", 1)[-1] != str(port):
            continue
        pid = int(fields[4])
        task = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
        match = re.match(r'"([^"]+)"', task.stdout.strip())
        executable_path = process_executable_path(pid)
        process_name = match.group(1) if match else (Path(executable_path).name if executable_path else process_image_name(pid))
        details = process_command_and_cwd(pid)
        kind = classify_process(process_name, details[0], details[1]) if details is not None else None
        parent_pid = details[2] if details is not None else 0
        return PortOwner(
            pid, process_name, kind or "unknown", parent_pid, executable_path,
            details[0] if details else None, details[1] if details else None,
        )
    return None


def process_executable_path(pid: int) -> str | None:
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
    finally:
        kernel.CloseHandle(handle)
    return None


def process_image_name(pid: int) -> str:
    path = process_executable_path(pid)
    return Path(path).name if path else "process name unavailable"


def _owner_description(owner: PortOwner | None) -> str:
    if owner is None:
        return "no process owner was reported"
    executable = f", executable {owner.executable_path}" if owner.executable_path else ""
    return f"PID {owner.pid} ({owner.name}{executable})"


def _port_state(owner: PortOwner | None, expected_kind: str) -> PortState:
    if owner is None:
        return PortState.FREE
    if owner.kind == expected_kind:
        return PortState.STALE_KYRA
    if owner.kind != "unknown" or owner.executable_path or owner.name != "process name unavailable":
        return PortState.UNRELATED
    return PortState.UNKNOWN


def verified_process_lineage(owner: PortOwner) -> list[PortOwner]:
    """Return the listener and only ancestors positively identified as the same KYRA service."""
    lineage = [owner]
    seen = {owner.pid}
    current = owner
    while current.parent_pid and current.parent_pid not in seen and len(lineage) < 8:
        seen.add(current.parent_pid)
        details = process_command_and_cwd(current.parent_pid)
        if details is None:
            break
        name = process_image_name(current.parent_pid)
        path = process_executable_path(current.parent_pid)
        kind = classify_process(name, details[0], details[1])
        if kind != owner.kind:
            break
        current = PortOwner(current.parent_pid, name, kind, details[2], path, details[0], details[1])
        lineage.append(current)
    return lineage


def stop_verified_stale_process(owner: PortOwner, port: int, expected_kind: str) -> None:
    """Stop a stale listener only after rechecking its port, executable, command, and checkout."""
    if os.name != "nt" or owner.pid <= 0 or owner.kind != expected_kind:
        raise RuntimeError(f"Cannot safely stop unresolved {expected_kind} owner on port {port}.")

    current_owner = process_using_port(port)
    if current_owner is None:
        return
    if current_owner.pid != owner.pid:
        raise RuntimeError(
            f"Port {port} changed owners during stale-process verification ({_owner_description(current_owner)}); "
            "no process was stopped."
        )
    current_details = process_command_and_cwd(owner.pid)
    current_name = process_image_name(owner.pid)
    current_executable = process_executable_path(owner.pid)
    if (
        current_details is None
        or classify_process(current_name, current_details[0], current_details[1]) != expected_kind
        or not current_executable
    ):
        raise RuntimeError(
            f"Port {port} listener PID {owner.pid} could not be reverified as this KYRA {expected_kind}; "
            "no process was stopped."
        )

    fresh_owner = PortOwner(
        owner.pid, current_name, expected_kind, current_details[2], current_executable,
        current_details[0], current_details[1],
    )
    lineage = verified_process_lineage(fresh_owner)
    stop_root = lineage[-1]
    print(f"[{expected_kind}] Stopping verified stale KYRA process tree rooted at PID {stop_root.pid}.")
    stopped = subprocess.run(
        ["taskkill", "/PID", str(stop_root.pid), "/T"], capture_output=True, text=True, check=False,
    )
    if stopped.returncode != 0:
        if process_using_port(port) is None:
            return
        raise RuntimeError(
            f"Could not stop verified stale KYRA {expected_kind} process tree rooted at PID {stop_root.pid}; "
            "no forced termination was attempted."
        )

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        remaining = process_using_port(port)
        if remaining is None:
            return
        if remaining.pid != owner.pid:
            raise RuntimeError(
                f"Port {port} is now occupied by {_owner_description(remaining)} after stopping stale KYRA; "
                "the new owner was left running."
            )
        time.sleep(0.2)
    raise RuntimeError(
        f"Verified stale KYRA process still occupies port {port} after a graceful stop request; "
        "no forced termination was attempted."
    )


def probe_backend(port: int, protocol: str, origin: str | None = None) -> BackendProbe:
    """Check the real health endpoint and, when requested, its exact CORS origin."""
    host = "localhost"
    url = f"{protocol}://{host}:{port}/api/health"
    headers = {"Accept": "application/json"}
    if origin:
        headers["Origin"] = origin
    context = None
    if protocol == "https":
        ca_file = ROOT / "dev-certs" / "kyra-dev-ca.crt"
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file.exists() else None)
    try:
        with urlopen(Request(url, headers=headers), timeout=2, context=context) as response:
            payload = json.loads(response.read(8192).decode("utf-8"))
            healthy = (
                response.status == 200
                and response.geturl() == url
                and isinstance(payload, dict)
                and payload.get("api") == "online"
                and isinstance(payload.get("configured"), dict)
                and isinstance(payload.get("ai"), dict)
            )
            cors_allowed = not origin or response.headers.get("Access-Control-Allow-Origin") == origin
            detail = f"HTTP {response.status}" if healthy else "response was not a KYRA health response"
            return BackendProbe(protocol, healthy, cors_allowed, detail)
    except Exception as cause:
        return BackendProbe(protocol, False, False, type(cause).__name__)


def inspect_backend(port: int, expected_protocol: str, frontend_origin: str) -> bool:
    """Reuse a matching KYRA backend, replace a verified stale one, or fail safely."""
    owner = process_using_port(port)
    state = _port_state(owner, "backend")
    expected = probe_backend(port, expected_protocol, frontend_origin)
    if expected.is_kyra:
        if state == PortState.UNRELATED:
            raise RuntimeError(
                f"[backend] Port {port} is occupied by an unrelated process ({_owner_description(owner)}). "
                "KYRA will not terminate or take over it."
            )
        if not expected.cors_allowed:
            if state == PortState.STALE_KYRA:
                print(f"[backend] Existing KYRA health endpoint has incompatible CORS configuration on port {port}.")
                stop_verified_stale_process(owner, port, "backend")  # type: ignore[arg-type]
                return False
            raise RuntimeError(
                f"[backend] Port {port} serves KYRA over {expected_protocol.upper()}, but its CORS policy "
                f"does not allow {frontend_origin}. The owner is not verified as a replaceable KYRA process."
            )
        state = PortState.HEALTHY_KYRA
        print(f"[backend] Existing healthy KYRA {expected_protocol.upper()} backend detected on port {port}; reusing it.")
        return True

    other_protocol = "https" if expected_protocol == "http" else "http"
    alternate = probe_backend(port, other_protocol)
    if alternate.is_kyra:
        state = PortState.PROTOCOL_MISMATCH
        if owner is not None and owner.kind == "backend":
            print(
                f"[backend] Verified KYRA backend on port {port} uses {other_protocol.upper()}; "
                f"switching it to {expected_protocol.upper()} for this launch."
            )
            stop_verified_stale_process(owner, port, "backend")
            return False
        raise RuntimeError(
            f"[backend] Existing healthy KYRA backend on port {port} uses {other_protocol.upper()}, but this mode "
            f"requires {expected_protocol.upper()} ({_owner_description(owner)}). No process was terminated. "
            "Use --lan or stop the existing KYRA launcher before switching to local HTTP mode."
        )

    if state == PortState.STALE_KYRA:
        # Retry both protocols to avoid treating a backend still finishing startup as stale.
        time.sleep(0.25)
        expected = probe_backend(port, expected_protocol, frontend_origin)
        alternate = probe_backend(port, other_protocol)
        if expected.is_kyra and expected.cors_allowed:
            print(f"[backend] Existing healthy KYRA {expected_protocol.upper()} backend detected on port {port}; reusing it.")
            return True
        if alternate.is_kyra:
            raise RuntimeError(
                f"[backend] Existing healthy KYRA backend on port {port} uses {other_protocol.upper()}, but this mode "
                f"requires {expected_protocol.upper()}. No process was terminated."
            )
        print(f"[backend] Verified KYRA backend on port {port} is stale or unhealthy; replacing that KYRA process only.")
        stop_verified_stale_process(owner, port, "backend")  # type: ignore[arg-type]
        return False

    if owner is not None:
        state_label = "unresolved process owner" if state == PortState.UNKNOWN else "unrelated process"
        raise RuntimeError(
            f"[backend] Port {port} is occupied by {state_label} ({_owner_description(owner)}); "
            f"health probes failed ({expected_protocol.upper()}: {expected.detail}; {other_protocol.upper()}: {alternate.detail}). "
            "KYRA will not terminate it."
        )
    return False


def probe_frontend(protocol: str, host: str, port: int) -> FrontendProbe:
    """Identify this Vite dashboard from its served entry point and runtime module."""
    base_url = f"{protocol}://{host}:{port}"
    context = None
    if protocol == "https":
        ca_file = ROOT / "dev-certs" / "kyra-dev-ca.crt"
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file.exists() else None)
    try:
        with urlopen(Request(f"{base_url}/", headers={"Accept": "text/html"}), timeout=2, context=context) as response:
            html = response.read(65536).decode("utf-8", "replace")
            if response.status != 200 or response.geturl() != f"{base_url}/" or "/@vite/client" not in html:
                return FrontendProbe(protocol, False, None, None, "entry point is not a Vite dashboard")
        with urlopen(Request(f"{base_url}/lib/api.ts", headers={"Accept": "text/javascript"}), timeout=2, context=context) as response:
            source = response.read(262144).decode("utf-8", "replace")
        mode = re.search(r'"MODE"\s*:\s*"([^"]+)"', source)
        agent_url = re.search(r'"VITE_AGENT_URL"\s*:\s*"([^"]+)"', source)
        if mode is None or agent_url is None:
            return FrontendProbe(protocol, False, None, None, "Vite module did not expose KYRA runtime settings")
        return FrontendProbe(protocol, True, mode.group(1), agent_url.group(1), "KYRA Vite module served")
    except Exception as cause:
        return FrontendProbe(protocol, False, None, None, type(cause).__name__)


def inspect_frontend(frontend_url: str, expected_mode: str, expected_agent_url: str) -> bool:
    """Reuse a matching KYRA dashboard, replace a verified stale one, or fail safely."""
    parsed = urlparse(frontend_url)
    if parsed.hostname is None or parsed.port is None:
        raise RuntimeError(f"Invalid dashboard URL: {frontend_url}")
    expected_protocol = parsed.scheme
    owner = process_using_port(parsed.port)
    state = _port_state(owner, "frontend")
    expected = probe_frontend(expected_protocol, parsed.hostname, parsed.port)
    if expected.is_kyra:
        if state == PortState.UNRELATED:
            raise RuntimeError(
                f"[frontend] Port {parsed.port} is occupied by an unrelated process ({_owner_description(owner)}). "
                "KYRA will not terminate or take over it."
            )
        if expected.mode != expected_mode or expected.agent_url != expected_agent_url:
            state = PortState.STALE_KYRA
            if owner is None or owner.kind != "frontend":
                raise RuntimeError(
                    f"[frontend] KYRA Vite on port {parsed.port} has mode {expected.mode!r} and API {expected.agent_url!r}; "
                    f"this mode requires {expected_mode!r} and API {expected_agent_url!r}, but its owner is not verified. "
                    "No process was terminated."
                )
            print(f"[frontend] Verified KYRA Vite on port {parsed.port} has stale mode/API configuration; replacing that KYRA process only.")
            stop_verified_stale_process(owner, parsed.port, "frontend")
            return False
        state = PortState.HEALTHY_KYRA
        print(f"[frontend] Existing healthy KYRA Vite detected on port {parsed.port}; reusing it.")
        return True

    other_protocol = "https" if expected_protocol == "http" else "http"
    alternate = probe_frontend(other_protocol, parsed.hostname, parsed.port)
    if alternate.is_kyra:
        state = PortState.PROTOCOL_MISMATCH
        if owner is not None and owner.kind == "frontend":
            print(f"[frontend] Verified KYRA Vite on port {parsed.port} uses the wrong protocol/mode; replacing that KYRA process only.")
            stop_verified_stale_process(owner, parsed.port, "frontend")
            return False
        raise RuntimeError(
            f"[frontend] KYRA Vite on port {parsed.port} serves over {other_protocol.upper()}, but this mode requires "
            f"{expected_protocol.upper()} ({_owner_description(owner)}). Its owner is not verified; no process was terminated."
        )

    if state == PortState.STALE_KYRA:
        time.sleep(0.25)
        expected = probe_frontend(expected_protocol, parsed.hostname, parsed.port)
        alternate = probe_frontend(other_protocol, parsed.hostname, parsed.port)
        if expected.is_kyra and expected.mode == expected_mode and expected.agent_url == expected_agent_url:
            print(f"[frontend] Existing healthy KYRA Vite detected on port {parsed.port}; reusing it.")
            return True
        if alternate.is_kyra:
            print(f"[frontend] Verified KYRA Vite on port {parsed.port} uses the wrong protocol/mode; replacing that KYRA process only.")
            stop_verified_stale_process(owner, parsed.port, "frontend")  # type: ignore[arg-type]
            return False
        print(f"[frontend] Verified KYRA Vite on port {parsed.port} is stale or unhealthy; replacing that KYRA process only.")
        stop_verified_stale_process(owner, parsed.port, "frontend")  # type: ignore[arg-type]
        return False

    if owner is not None:
        state_label = "unresolved process owner" if state == PortState.UNKNOWN else "unrelated process"
        raise RuntimeError(
            f"[frontend] Port {parsed.port} is occupied by {state_label} ({_owner_description(owner)}) and did not serve "
            f"a KYRA dashboard ({expected_protocol.upper()}: {expected.detail}; {other_protocol.upper()}: {alternate.detail}). "
            "KYRA will not terminate it."
        )
    return False


def ensure_lan_certificate(address: str, python: str) -> None:
    certificate = ROOT / "dev-certs" / "kyra-lan-cert.pem"
    matches = False
    if certificate.exists():
        try:
            names = ssl._ssl._test_decode_cert(str(certificate)).get("subjectAltName", ())
            matches = ("IP Address", address) in names
        except (OSError, ssl.SSLError, ValueError):
            matches = False
    if matches:
        return

    command = [python, str(ROOT / "scripts" / "generate_lan_dev_certificate.py"), address]
    if any((ROOT / "dev-certs" / filename).exists() for filename in (
        "kyra-dev-ca-key.pem", "kyra-dev-ca.crt", "kyra-lan-key.pem", "kyra-lan-cert.pem",
    )):
        command.append("--force")
    subprocess.run(command, cwd=ROOT, check=True)
    print("The LAN certificate changed. Import dev-certs/kyra-dev-ca.crt into each browser device's trusted root store.")


def wait_for_backend(port: int, protocol: str, origin: str, process: subprocess.Popen, timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Backend exited during startup; see the backend error above.")
        result = probe_backend(port, protocol, origin)
        if result.is_kyra and result.cors_allowed:
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Backend did not pass its {protocol.upper()} health and CORS check within {timeout:g} seconds."
    )


def wait_for_frontend(url: str, mode: str, agent_url: str, process: subprocess.Popen, timeout: float = 20) -> None:
    parsed = urlparse(url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Frontend exited during startup; see the frontend error above.")
        result = probe_frontend(parsed.scheme, parsed.hostname or "localhost", parsed.port or FRONTEND_PORT)
        if result.is_kyra and result.mode == mode and result.agent_url == agent_url:
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Frontend did not serve the expected {mode!r} dashboard/API configuration within {timeout:g} seconds."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Start KYRA's FastAPI agent and Vite dashboard with shared network settings.")
    parser.add_argument("--lan", action="store_true", help="Serve HTTPS on the current LAN address for camera and microphone access.")
    args = parser.parse_args()

    python = sys.executable
    try:
        address = current_lan_ip() if args.lan else "localhost"
        backend_protocol = "https" if args.lan else "http"
        frontend_protocol = "https" if args.lan else "http"
        frontend_url = f"{frontend_protocol}://{address}:{FRONTEND_PORT}"
        backend_url = f"{backend_protocol}://{address}:{BACKEND_PORT}"
        bind_host = APP_HOST if args.lan else "127.0.0.1"
        frontend_origins = ",".join((
            f"http://localhost:{FRONTEND_PORT}",
            f"http://127.0.0.1:{FRONTEND_PORT}",
            frontend_url,
        ))

        # Probe the actual services before deciding whether either process needs to start.
        # This also catches a healthy KYRA service running with the opposite protocol.
        backend_reused = inspect_backend(BACKEND_PORT, backend_protocol, frontend_url)
        frontend_reused = inspect_frontend(frontend_url, "lan" if args.lan else "development", backend_url)
        if args.lan and (not backend_reused or not frontend_reused):
            ensure_lan_certificate(address, python)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as cause:
        print(f"KYRA startup failed: {cause}", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment.update({
        "APP_HOST": bind_host,
        "APP_PORT": str(BACKEND_PORT),
        "FRONTEND_URL": frontend_origins,
        "AGENT_URL": backend_url,
        "VITE_AGENT_URL": backend_url,
    })
    backend_command = [python, "-m", "uvicorn", "backend.app.main:app", "--host", bind_host, "--port", str(BACKEND_PORT), "--reload"]
    npm = "npm.cmd" if os.name == "nt" else "npm"
    frontend_command = [npm, "--prefix", "frontend", "run", "dev", "--", "--host", bind_host, "--port", str(FRONTEND_PORT), "--strictPort"]
    if args.lan:
        certs = ROOT / "dev-certs"
        backend_command.extend(["--ssl-certfile", str(certs / "kyra-lan-cert.pem"), "--ssl-keyfile", str(certs / "kyra-lan-key.pem")])
        environment["KYRA_DEV_HTTPS"] = "true"
        frontend_command = [npm, "--prefix", "frontend", "run", "dev:lan"]
    else:
        environment.pop("KYRA_DEV_HTTPS", None)
        environment.pop("KYRA_DEV_TLS_CERT", None)
        environment.pop("KYRA_DEV_TLS_KEY", None)

    children: list[subprocess.Popen] = []
    try:
        if not backend_reused:
            backend_process = subprocess.Popen(backend_command, cwd=ROOT, env=environment)
            children.append(backend_process)
            wait_for_backend(BACKEND_PORT, backend_protocol, frontend_url, backend_process)
        if not frontend_reused:
            frontend_process = subprocess.Popen(frontend_command, cwd=ROOT, env=environment)
            children.append(frontend_process)
            wait_for_frontend(frontend_url, "lan" if args.lan else "development", backend_url, frontend_process)
        print(f"KYRA dashboard: {frontend_url}", flush=True)
        print(f"KYRA API and /ws/agent: {backend_url}", flush=True)
        if not children:
            print("Both services are already healthy and match this mode; no duplicate processes were started.", flush=True)
            return 0
        print("Press Ctrl+C to stop services started by this launcher.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return next((child.returncode or 0 for child in children if child.poll() is not None), 0)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as cause:
        print(f"KYRA startup failed: {cause}", file=sys.stderr)
        return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            if child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
