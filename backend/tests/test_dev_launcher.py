import subprocess
import re

import pytest

from scripts.dev import (
    BackendProbe,
    FrontendProbe,
    PortOwner,
    ROOT,
    classify_process,
    inspect_backend,
    inspect_frontend,
    main,
)


def test_supported_kyra_uvicorn_working_directories_are_classified_as_backend() -> None:
    command = "python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
    backend_command = "python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

    assert classify_process("python.exe", command, str(ROOT)) == "backend"
    assert classify_process("python.exe", backend_command, str(ROOT / "backend")) == "backend"
    assert classify_process("python.exe", command, str(ROOT.parent)) is None
    assert classify_process("python.exe", "python.exe -m uvicorn other_app:app", str(ROOT)) is None


def test_only_vite_from_kyra_frontend_is_classified_as_frontend() -> None:
    command = 'node.exe "D:\\KYRA\\frontend\\node_modules\\vite\\bin\\vite.js" --host 0.0.0.0'

    assert classify_process("node.exe", command, str(ROOT / "frontend")) == "frontend"
    assert classify_process("node.exe", command, str(ROOT / "other-frontend")) is None
    assert classify_process("node.exe", "node.exe server.js", str(ROOT / "frontend")) is None


def test_free_backend_port_is_reported_as_available(monkeypatch) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: None)
    monkeypatch.setattr("scripts.dev.probe_backend", lambda _port, protocol, _origin=None: BackendProbe(protocol, False, False, "connection refused"))

    assert inspect_backend(8000, "http", "http://localhost:5173") is False


def test_healthy_http_backend_is_reused(monkeypatch) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: PortOwner(101, "python.exe", "backend"))
    monkeypatch.setattr(
        "scripts.dev.probe_backend",
        lambda _port, protocol, origin=None: BackendProbe(protocol, protocol == "http", origin == "http://localhost:5173", "HTTP 200"),
    )

    assert inspect_backend(8000, "http", "http://localhost:5173") is True


def test_healthy_matching_backend_is_reused_even_when_owner_is_unresolvable(monkeypatch) -> None:
    owner = PortOwner(5876, "process name unavailable", "unknown")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr(
        "scripts.dev.probe_backend",
        lambda _port, protocol, origin=None: BackendProbe(protocol, protocol == "https", origin == "https://kyra-host.test:5173", "HTTP 200"),
    )

    assert inspect_backend(8000, "https", "https://kyra-host.test:5173") is True


def test_verified_backend_with_wrong_protocol_is_restarted_for_requested_mode(monkeypatch) -> None:
    owner = PortOwner(5876, "python.exe", "backend", executable_path="D:\\KYRA\\.venv\\Scripts\\python.exe")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr(
        "scripts.dev.probe_backend",
        lambda _port, protocol, _origin=None: BackendProbe(protocol, protocol == "https", False, "HTTP 200" if protocol == "https" else "RemoteDisconnected"),
    )
    stopped = []
    monkeypatch.setattr("scripts.dev.stop_verified_stale_process", lambda actual, port, kind: stopped.append((actual, port, kind)))

    assert inspect_backend(8000, "http", "http://localhost:5173") is False
    assert stopped == [(owner, 8000, "backend")]


def test_backend_reuse_requires_matching_cors_origin(monkeypatch) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: None)
    monkeypatch.setattr("scripts.dev.probe_backend", lambda _port, protocol, _origin=None: BackendProbe(protocol, True, False, "HTTP 200"))

    with pytest.raises(RuntimeError, match="does not allow http://localhost:5173"):
        inspect_backend(8000, "http", "http://localhost:5173")


def test_identifiable_unrelated_backend_owner_is_reported_and_left_running(monkeypatch) -> None:
    owner = PortOwner(202, "other.exe", "unknown", executable_path=r"C:\Tools\other.exe")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr("scripts.dev.probe_backend", lambda _port, protocol, _origin=None: BackendProbe(protocol, False, False, "connection refused"))

    with pytest.raises(RuntimeError, match=r"Port 8000.*PID 202.*" + re.escape(owner.executable_path)):
        inspect_backend(8000, "http", "http://localhost:5173")


def test_stale_verified_backend_is_safely_replaced(monkeypatch) -> None:
    owner = PortOwner(204, "python.exe", "backend", executable_path="D:\\KYRA\\.venv\\Scripts\\python.exe")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr("scripts.dev.probe_backend", lambda _port, protocol, _origin=None: BackendProbe(protocol, False, False, "connection refused"))
    stopped = []
    monkeypatch.setattr("scripts.dev.stop_verified_stale_process", lambda actual, port, kind: stopped.append((actual, port, kind)))
    monkeypatch.setattr("scripts.dev.time.sleep", lambda _duration: None)

    assert inspect_backend(8000, "http", "http://localhost:5173") is False
    assert stopped == [(owner, 8000, "backend")]


def test_unknown_backend_owner_is_never_terminated(monkeypatch) -> None:
    owner = PortOwner(205, "process name unavailable", "unknown")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr("scripts.dev.probe_backend", lambda _port, protocol, _origin=None: BackendProbe(protocol, False, False, "connection refused"))
    monkeypatch.setattr("scripts.dev.stop_verified_stale_process", lambda *_args: pytest.fail("unknown owner must not be stopped"))

    with pytest.raises(RuntimeError, match="unresolved process owner"):
        inspect_backend(8000, "http", "http://localhost:5173")


def test_stale_stop_revalidates_pid_and_uses_graceful_process_tree_stop(monkeypatch) -> None:
    import scripts.dev as launcher

    if launcher.os.name != "nt":
        pytest.skip("Windows process-tree termination is specific to Windows.")
    owner = PortOwner(210, "python.exe", "backend", executable_path="D:\\KYRA\\.venv\\Scripts\\python.exe")
    port_owners = iter((owner, None))
    commands = []
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: next(port_owners))
    monkeypatch.setattr("scripts.dev.process_command_and_cwd", lambda _pid: ("python -m uvicorn backend.app.main:app", str(ROOT), 0))
    monkeypatch.setattr("scripts.dev.process_image_name", lambda _pid: "python.exe")
    monkeypatch.setattr("scripts.dev.process_executable_path", lambda _pid: owner.executable_path)
    monkeypatch.setattr("scripts.dev.verified_process_lineage", lambda actual: [actual])
    monkeypatch.setattr(
        "scripts.dev.subprocess.run",
        lambda command, **_kwargs: (commands.append(command) or subprocess.CompletedProcess(command, 0)),
    )

    launcher.stop_verified_stale_process(owner, 8000, "backend")

    assert commands == [["taskkill", "/PID", "210", "/T"]]


def test_healthy_local_frontend_is_reused(monkeypatch) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: PortOwner(203, "node.exe", "frontend"))
    monkeypatch.setattr(
        "scripts.dev.probe_frontend",
        lambda protocol, _host, _port: FrontendProbe(protocol, True, "development", "http://localhost:8000", "KYRA Vite module served"),
    )

    assert inspect_frontend("http://localhost:5173", "development", "http://localhost:8000") is True


def test_free_frontend_port_is_reported_as_available(monkeypatch) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: None)
    monkeypatch.setattr("scripts.dev.probe_frontend", lambda protocol, _host, _port: FrontendProbe(protocol, False, None, None, "connection refused"))

    assert inspect_frontend("http://localhost:5173", "development", "http://localhost:8000") is False


def test_stale_verified_frontend_is_safely_replaced(monkeypatch) -> None:
    owner = PortOwner(206, "node.exe", "frontend", executable_path="C:\\Program Files\\nodejs\\node.exe")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr("scripts.dev.probe_frontend", lambda protocol, _host, _port: FrontendProbe(protocol, False, None, None, "connection refused"))
    stopped = []
    monkeypatch.setattr("scripts.dev.stop_verified_stale_process", lambda actual, port, kind: stopped.append((actual, port, kind)))
    monkeypatch.setattr("scripts.dev.time.sleep", lambda _duration: None)

    assert inspect_frontend("http://localhost:5173", "development", "http://localhost:8000") is False
    assert stopped == [(owner, 5173, "frontend")]


def test_verified_frontend_with_wrong_mode_is_replaced(monkeypatch) -> None:
    owner = PortOwner(207, "node.exe", "frontend", executable_path="C:\\Program Files\\nodejs\\node.exe")
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr(
        "scripts.dev.probe_frontend",
        lambda protocol, _host, _port: FrontendProbe(protocol, True, "lan", "https://kyra-host.test:8000", "KYRA Vite module served"),
    )
    stopped = []
    monkeypatch.setattr("scripts.dev.stop_verified_stale_process", lambda actual, port, kind: stopped.append((actual, port, kind)))

    assert inspect_frontend("http://localhost:5173", "development", "http://localhost:8000") is False
    assert stopped == [(owner, 5173, "frontend")]


def test_frontend_runtime_must_match_page_mode_and_backend_protocol(monkeypatch) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: None)
    monkeypatch.setattr(
        "scripts.dev.probe_frontend",
        lambda protocol, _host, _port: FrontendProbe(protocol, True, "lan", "https://kyra-host.test:8000", "KYRA Vite module served"),
    )

    with pytest.raises(RuntimeError, match="mode 'lan'.*requires 'development'"):
        inspect_frontend("http://localhost:5173", "development", "http://localhost:8000")


@pytest.mark.parametrize("owner", (
    PortOwner(208, "other.exe", "unknown", executable_path="C:\\Tools\\other.exe"),
    PortOwner(209, "process name unavailable", "unknown"),
))
def test_unrelated_or_unknown_frontend_owner_is_never_terminated(monkeypatch, owner) -> None:
    monkeypatch.setattr("scripts.dev.process_using_port", lambda _port: owner)
    monkeypatch.setattr("scripts.dev.probe_frontend", lambda protocol, _host, _port: FrontendProbe(protocol, False, None, None, "connection refused"))
    monkeypatch.setattr("scripts.dev.stop_verified_stale_process", lambda *_args: pytest.fail("unverified owner must not be stopped"))

    with pytest.raises(RuntimeError, match="will not terminate it"):
        inspect_frontend("http://localhost:5173", "development", "http://localhost:8000")


class _FakeProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.returncode = None
        self._poll_count = 0

    def poll(self):
        self._poll_count += 1
        if self._poll_count >= 2:
            self.returncode = 0
            return 0
        return None

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode or 0


def _prepare_startup(monkeypatch, *, lan: bool, backend_reused: bool, frontend_reused: bool):
    commands = []
    monkeypatch.setattr("scripts.dev.sys.argv", ["dev.py", *( ["--lan"] if lan else [])])
    monkeypatch.setattr("scripts.dev.inspect_backend", lambda *_args: backend_reused)
    monkeypatch.setattr("scripts.dev.inspect_frontend", lambda *_args: frontend_reused)
    monkeypatch.setattr("scripts.dev.subprocess.Popen", lambda command, **kwargs: (commands.append((command, kwargs)) or _FakeProcess(command, **kwargs)))
    monkeypatch.setattr("scripts.dev.time.sleep", lambda _duration: None)
    monkeypatch.setattr("scripts.dev.wait_for_backend", lambda *_args: None)
    monkeypatch.setattr("scripts.dev.wait_for_frontend", lambda *_args: None)
    monkeypatch.setattr("scripts.dev.ensure_lan_certificate", lambda *_args: None)
    return commands


def test_local_startup_starts_http_backend_and_frontend(monkeypatch) -> None:
    commands = _prepare_startup(monkeypatch, lan=False, backend_reused=False, frontend_reused=False)

    assert main() == 0
    assert len(commands) == 2
    backend_command, backend_options = commands[0]
    frontend_command, frontend_options = commands[1]
    assert "--host" in backend_command and backend_command[backend_command.index("--host") + 1] == "127.0.0.1"
    assert "--ssl-certfile" not in backend_command
    assert frontend_command[0].endswith("npm.cmd")
    assert "dev" in frontend_command
    assert backend_options["env"]["AGENT_URL"] == "http://localhost:8000"
    assert backend_options["env"]["APP_HOST"] == "127.0.0.1"
    assert "KYRA_DEV_HTTPS" not in backend_options["env"]
    assert frontend_options["env"]["VITE_AGENT_URL"] == "http://localhost:8000"


def test_lan_startup_uses_dynamic_https_urls_and_tls(monkeypatch) -> None:
    commands = _prepare_startup(monkeypatch, lan=True, backend_reused=False, frontend_reused=False)
    monkeypatch.setattr("scripts.dev.current_lan_ip", lambda: "10.12.0.44")

    assert main() == 0
    assert len(commands) == 2
    backend_command, options = commands[0]
    assert "--ssl-certfile" in backend_command
    assert "10.12.0.44" not in " ".join(backend_command)
    assert options["env"]["AGENT_URL"] == "https://10.12.0.44:8000"
    assert options["env"]["VITE_AGENT_URL"] == "https://10.12.0.44:8000"
    assert options["env"]["KYRA_DEV_HTTPS"] == "true"


def test_reusing_both_services_starts_no_duplicate_uvicorn_or_vite(monkeypatch) -> None:
    commands = _prepare_startup(monkeypatch, lan=True, backend_reused=True, frontend_reused=True)
    monkeypatch.setattr("scripts.dev.current_lan_ip", lambda: "10.12.0.44")

    assert main() == 0
    assert commands == []
