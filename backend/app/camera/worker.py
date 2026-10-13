from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable

from app.camera.service import CameraService
from app.gestures.engine import GestureDetection, Landmark
from app.gestures.runtime import GestureRuntime

logger = logging.getLogger("kyra.camera")


@dataclass(frozen=True)
class CameraFrameSnapshot:
    preview: str | None
    hands: tuple[tuple[Landmark, ...], ...]
    updated_at: float


DetectionHandler = Callable[[GestureDetection], None]


class CameraWorker:
    """Processes local camera frames on an agent-owned thread, independent of the UI tab."""

    def __init__(
        self,
        camera: CameraService,
        runtime: GestureRuntime,
        on_detection: DetectionHandler,
        *,
        preview_interval: float = 0.1,
        frame_interval: float = 1 / 30,
    ) -> None:
        self._camera = camera
        self._runtime = runtime
        self._on_detection = on_detection
        self._preview_interval = preview_interval
        self._frame_interval = frame_interval
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._snapshot = CameraFrameSnapshot(preview=None, hands=(), updated_at=0)
        self._error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def snapshot(self) -> CameraFrameSnapshot:
        with self._lock:
            return self._snapshot

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="kyra-camera-analysis", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("Camera analysis did not stop in time.")
        self._thread = None

    def _run(self) -> None:
        next_preview = 0.0
        try:
            while not self._stop.is_set():
                frame_started = monotonic()
                frame = self._camera.read_frame()
                result = self._runtime.process_frame(frame, frame_started)
                now = monotonic()
                preview = None
                if now >= next_preview:
                    try:
                        preview = self._camera.preview_data_url(frame)
                    except Exception as cause:
                        logger.warning("camera_preview_encoding_failed", extra={"error_type": type(cause).__name__})
                    next_preview = now + self._preview_interval
                with self._lock:
                    self._snapshot = CameraFrameSnapshot(
                        preview=preview if preview is not None else self._snapshot.preview,
                        hands=result.hands,
                        updated_at=now,
                    )
                for detection in result.detections:
                    self._on_detection(detection)
                self._stop.wait(max(0.0, self._frame_interval - (monotonic() - frame_started)))
        except Exception as cause:
            with self._lock:
                self._error = "Camera analysis stopped unexpectedly."
            logger.exception("camera_background_processing_failed", extra={"error_type": type(cause).__name__})
            try:
                self._runtime.stop()
            except Exception:
                logger.exception("camera_runtime_cleanup_failed")
            self._camera.stop()
