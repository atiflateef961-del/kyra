from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol


@dataclass(frozen=True)
class ForegroundWindow:
    process_name: str
    title: str


class ForegroundReader(Protocol):
    def read(self) -> ForegroundWindow | None: ...


class WindowsForegroundReader:
    """Reads the foreground window locally. It never launches the process it sees."""

    def read(self) -> ForegroundWindow | None:
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return None

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_win32_signatures(user32, kernel32, ctypes, wintypes)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buffer = ctypes.create_unicode_buffer(min(length, 512) + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            title = buffer.value

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        handle = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not handle:
            return ForegroundWindow(process_name="unknown", title=title)
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(32768)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return ForegroundWindow(process_name="unknown", title=title)
            process_name = path.value.replace("/", "\\").rsplit("\\", 1)[-1]
        finally:
            kernel32.CloseHandle(handle)
        if not process_name or ".." in process_name or "/" in process_name or "\\" in process_name:
            process_name = "unknown"
        return ForegroundWindow(process_name=process_name, title=title)


def _configure_win32_signatures(user32, kernel32, ctypes, wintypes) -> None:
    """Keep HWND/HANDLE values pointer-sized on 64-bit Windows."""
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
