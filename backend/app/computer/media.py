from __future__ import annotations

import asyncio
import importlib
import os
from threading import Event, Thread
from typing import Any


class MediaSessionError(RuntimeError):
    """Raised when a precise Windows media-session request cannot be made."""


class WindowsMediaSessionControl:
    """Send idempotent play/pause requests through Windows media sessions."""

    def __init__(
        self,
        *,
        module: Any | None = None,
        timeout_seconds: float = 3.0,
        platform: str | None = None,
    ) -> None:
        self._module = module
        self._timeout = timeout_seconds
        self._platform = platform or os.name

    def control(self, action: str) -> None:
        if self._platform != "nt":
            raise MediaSessionError("Windows media-session control is only available on Windows.")
        if action not in {"play", "pause"}:
            raise MediaSessionError("Media action is not supported.")
        try:
            module = self._module or importlib.import_module("winrt.windows.media.control")
        except ImportError as cause:
            raise MediaSessionError("Windows media-session support is unavailable; install the backend dependencies.") from cause

        completed = Event()
        outcome: dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["result"] = asyncio.run(self._control_async(module, action))
            except Exception as cause:
                outcome["error"] = cause
            finally:
                completed.set()

        worker = Thread(target=run, name="kyra-media-session", daemon=True)
        worker.start()
        if not completed.wait(self._timeout + 0.5):
            raise MediaSessionError("Windows media-session request timed out.")
        cause = outcome.get("error")
        if cause is not None:
            if isinstance(cause, MediaSessionError):
                raise cause
            if isinstance(cause, OSError) and cause.args and cause.args[0] == -2147023836:
                raise MediaSessionError("Windows media-session service is unavailable in this session.") from cause
            raise MediaSessionError("Windows media-session request failed.") from cause
        if outcome.get("result") is not True:
            raise MediaSessionError(f"Windows media session did not accept the {action} request.")

    async def _control_async(self, module: Any, action: str) -> bool:
        async def request() -> bool:
            manager = await module.GlobalSystemMediaTransportControlsSessionManager.request_async()
            session = manager.get_current_session()
            if session is None:
                raise MediaSessionError("No active Windows media session was found.")
            operation = session.try_play_async() if action == "play" else session.try_pause_async()
            return bool(await operation)

        try:
            return await asyncio.wait_for(request(), timeout=self._timeout)
        except asyncio.TimeoutError as cause:
            raise MediaSessionError("Windows media-session request timed out.") from cause
