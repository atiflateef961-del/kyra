from __future__ import annotations

import importlib
import base64
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from app.contracts.models import CameraStatus


class CameraUnavailable(RuntimeError):
    """Raised when camera capture cannot safely start or provide a frame."""


class CaptureDevice(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def release(self) -> None: ...


def _load_opencv() -> Any | None:
    try:
        return importlib.import_module("cv2")
    except ImportError:
        return None


class CameraService:
    """Owns one local capture resource and never opens it during construction."""

    def __init__(
        self,
        device_index: int = 0,
        *,
        capture_factory: Callable[[int], CaptureDevice] | None = None,
        opencv_module: Any | None = None,
    ) -> None:
        if device_index < 0:
            raise ValueError("Camera device index must be zero or greater.")
        self._device_index = device_index
        self._opencv = opencv_module if opencv_module is not None else _load_opencv()
        self._capture_factory = capture_factory
        self._capture: CaptureDevice | None = None
        self._first_frame: Any | None = None
        self._available: bool | None = None
        self._message = "Camera availability has not been checked."
        self._diagnostic_code = "not_checked"

    def status(self) -> CameraStatus:
        return CameraStatus(
            available=self._available,
            active=self._capture is not None,
            updated_at=datetime.now(UTC),
            message=self._message,
            diagnostic_code=self._diagnostic_code,
        )

    def probe(self) -> CameraStatus:
        """Check a device on demand and release it immediately if capture is inactive."""
        if self._capture is not None:
            self._available = True
            self._message = "Camera capture is active."
            return self.status()
        if self._opencv is None and self._capture_factory is None:
            self._available = False
            self._message = "OpenCV is not installed; camera control is unavailable."
            return self.status()

        try:
            capture = self._new_capture()
        except Exception as cause:
            self._set_failure("initialization_failed", f"Camera initialization failed ({type(cause).__name__}).")
            return self.status()
        try:
            if not capture.isOpened():
                self._set_failure("device_unavailable", "No camera capture device could be opened.")
                return self.status()
            success, frame = capture.read()
            if not success or frame is None:
                self._set_failure("no_data", "Camera opened but did not provide a frame.")
                return self.status()
            self._available = True
            self._diagnostic_code = "ready"
            self._message = "Camera opened and provided a frame."
        except Exception as cause:
            self._set_failure("frame_read_failed", f"Camera frame read failed ({type(cause).__name__}).")
        finally:
            capture.release()
        return self.status()

    def start(self) -> CameraStatus:
        """Open the selected local device only after an explicit caller request."""
        if self._capture is not None:
            return self.status()
        if self._opencv is None and self._capture_factory is None:
            self._available = False
            self._message = "OpenCV is not installed; camera control is unavailable."
            raise CameraUnavailable(self._message)

        try:
            capture = self._new_capture()
            if not capture.isOpened():
                self._set_failure("device_unavailable", "No camera capture device could be opened.")
                capture.release()
                raise CameraUnavailable(self._message)
            success, frame = capture.read()
            if not success or frame is None:
                self._set_failure("no_data", "Camera opened but did not provide a frame.")
                capture.release()
                raise CameraUnavailable(self._message)
        except CameraUnavailable:
            raise
        except Exception as cause:
            self._set_failure("initialization_failed", f"Camera initialization failed ({type(cause).__name__}).")
            if "capture" in locals():
                capture.release()
            raise CameraUnavailable(self._message) from cause
        self._capture = capture
        self._first_frame = frame
        self._available = True
        self._message = "Camera capture is active."
        self._diagnostic_code = "ready"
        return self.status()

    def read_frame(self) -> Any:
        if self._capture is None:
            raise CameraUnavailable("Camera capture is not active.")
        if self._first_frame is not None:
            frame, self._first_frame = self._first_frame, None
            return frame
        success, frame = self._capture.read()
        if not success or frame is None:
            self._set_failure("no_data", "Camera capture did not provide a frame.")
            raise CameraUnavailable("Camera did not provide a frame.")
        return frame

    def preview_data_url(self, frame: Any) -> str | None:
        """Encode the current frame for the authenticated dashboard; never writes it to disk."""
        if self._opencv is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
            return None
        mirrored = self._opencv.flip(frame, 1)
        height, width = mirrored.shape[:2]
        if width > 480:
            mirrored = self._opencv.resize(mirrored, (480, round(height * 480 / width)))
        quality = [self._opencv.IMWRITE_JPEG_QUALITY, 60]
        encoded, buffer = self._opencv.imencode(".jpg", mirrored, quality)
        if not encoded:
            raise CameraUnavailable("The live camera preview could not be encoded.")
        return "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")

    def stop(self) -> CameraStatus:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._first_frame = None
        if self._available is True:
            self._message = "Camera is available but inactive."
            self._diagnostic_code = "ready"
        return self.status()

    def _set_failure(self, code: str, message: str) -> None:
        self._available = False
        self._diagnostic_code = code
        self._message = message

    def _new_capture(self) -> CaptureDevice:
        if self._capture_factory is not None:
            return self._capture_factory(self._device_index)
        assert self._opencv is not None
        # OpenCV's default Windows backend can report no device even when a
        # webcam is available. DirectShow is reliable for the local agent's
        # device-index capture path; other platforms keep OpenCV's default.
        if os.name == "nt" and hasattr(self._opencv, "CAP_DSHOW"):
            return self._opencv.VideoCapture(self._device_index, self._opencv.CAP_DSHOW)
        return self._opencv.VideoCapture(self._device_index)
