from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event
from typing import Any

from app.contracts.models import MicrophoneStatus


class MicrophoneUnavailable(RuntimeError):
    """Raised only after an explicit microphone start is requested."""


def _load_sounddevice() -> Any | None:
    try:
        return importlib.import_module("sounddevice")
    except ImportError:
        return None


_AUTO_LOAD = object()


class MicrophoneService:
    """Owns an opt-in local input stream and never stores captured audio."""

    def __init__(self, device_index: int | None = None, sounddevice_module: Any = _AUTO_LOAD) -> None:
        self._device_index = device_index
        self._sounddevice = _load_sounddevice() if sounddevice_module is _AUTO_LOAD else sounddevice_module
        self._stream: Any | None = None
        self._available: bool | None = None
        self._message = "Microphone availability has not been checked."
        self._diagnostic_code = "not_checked"
        self._diagnostic_detail: str | None = None

    def status(self) -> MicrophoneStatus:
        active = self._stream is not None
        if active and getattr(self._stream, "active", True) is False:
            active = False
            self._available = False
            self._diagnostic_code = "stream_stopped"
            self._diagnostic_detail = None
            self._message = "Microphone capture stopped unexpectedly."
        return MicrophoneStatus(
            available=self._available,
            active=active,
            updated_at=datetime.now(UTC),
            message=self._message,
            diagnostic_code=self._diagnostic_code,
            diagnostic_detail=self._diagnostic_detail,
        )

    def probe(self) -> MicrophoneStatus:
        if self._sounddevice is None:
            self._available = False
            self._diagnostic_code = "dependency_unavailable"
            self._diagnostic_detail = None
            self._message = "sounddevice is not installed; microphone control is unavailable."
            return self.status()
        if self._stream is not None:
            return self.status()
        received_audio = Event()
        try:
            self.start(lambda _audio: received_audio.set())
        except MicrophoneUnavailable:
            return self.status()
        if not received_audio.wait(0.75):
            self.stop()
            self._available = False
            self._diagnostic_code = "no_data"
            self._diagnostic_detail = None
            self._message = "Microphone stream started but no audio samples arrived within 750 ms."
            return self.status()
        return self.stop()

    def start(self, on_audio: Callable[[Any], None] | None = None) -> MicrophoneStatus:
        if self._stream is not None:
            return self.status()
        if self._sounddevice is None:
            self._available = False
            self._diagnostic_code = "dependency_unavailable"
            self._diagnostic_detail = None
            self._message = "sounddevice is not installed; microphone control is unavailable."
            raise MicrophoneUnavailable(self._message)

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            # Audio stays in process memory and is immediately passed to the caller.
            if on_audio is not None:
                on_audio(indata.copy())

        stream: Any | None = None
        try:
            stream = self._sounddevice.InputStream(
                device=self._device_index,
                samplerate=16_000,
                channels=1,
                dtype="float32",
                callback=callback,
            )
            stream.start()
        except Exception as cause:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            self._available = False
            code, detail = self._classify_failure(cause)
            self._diagnostic_code = code
            self._diagnostic_detail = detail
            self._message = f"Microphone initialization failed ({detail or type(cause).__name__}). Check Windows desktop-app microphone access and whether another app is using the device."
            raise MicrophoneUnavailable(self._message) from cause
        self._stream = stream
        self._available = True
        self._message = "Microphone capture is active."
        self._diagnostic_code = "ready"
        self._diagnostic_detail = None
        return self.status()

    def stop(self) -> MicrophoneStatus:
        stream, self._stream = self._stream, None
        if stream is not None:
            failure: Exception | None = None
            try:
                stream.stop()
            except Exception as cause:
                failure = cause
            finally:
                try:
                    stream.close()
                except Exception as cause:
                    failure = failure or cause
            if failure is not None:
                self._available = False
                self._diagnostic_code = "cleanup_failed"
                self._diagnostic_detail = type(failure).__name__
                self._message = f"Microphone stream cleanup failed ({type(failure).__name__})."
                return self.status()
        if self._available is True:
            self._message = "Microphone is available but inactive."
            self._diagnostic_code = "ready"
        return self.status()

    @staticmethod
    def _classify_failure(cause: Exception) -> tuple[str, str]:
        arguments = getattr(cause, "args", ())
        portaudio_code = arguments[1] if len(arguments) > 1 and isinstance(arguments[1], int) else None
        host_code = None
        if len(arguments) > 2 and isinstance(arguments[2], tuple) and len(arguments[2]) > 1:
            candidate = arguments[2][1]
            if isinstance(candidate, int):
                host_code = candidate

        text = str(cause).casefold()
        if "permission" in text or "access denied" in text or "not permitted" in text:
            diagnostic = "permission_denied"
        elif "busy" in text or "in use" in text:
            diagnostic = "device_busy"
        elif portaudio_code == -9996:
            diagnostic = "device_unavailable"
        elif portaudio_code == -9997:
            diagnostic = "unsupported_sample_rate"
        elif portaudio_code == -9998:
            diagnostic = "unsupported_channel_count"
        else:
            diagnostic = "initialization_failed"

        detail_parts = [type(cause).__name__]
        if portaudio_code is not None:
            detail_parts.append(f"PortAudio {portaudio_code}")
        if host_code is not None:
            detail_parts.append(f"host error {host_code}")
        return diagnostic, "; ".join(detail_parts)
