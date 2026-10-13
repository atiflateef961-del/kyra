from __future__ import annotations

import importlib
from typing import Any


class VisionDependencyUnavailable(RuntimeError):
    """Raised only when MediaPipe hand processing is explicitly requested."""


def _load_mediapipe() -> Any | None:
    try:
        return importlib.import_module("mediapipe")
    except ImportError:
        return None


class MediaPipeHandsProcessor:
    """Local hand-landmark processor; gesture interpretation belongs to Task 13."""

    def __init__(self, mediapipe_module: Any | None = None) -> None:
        self._mediapipe = mediapipe_module if mediapipe_module is not None else _load_mediapipe()
        self._hands: Any | None = None

    @property
    def available(self) -> bool:
        return (
            self._mediapipe is not None
            and hasattr(self._mediapipe, "solutions")
            and hasattr(self._mediapipe.solutions, "hands")
        )

    def start(self) -> None:
        if self._mediapipe is None:
            raise VisionDependencyUnavailable("MediaPipe is not installed; hand landmarks are unavailable.")
        if not self.available:
            raise VisionDependencyUnavailable(
                "The installed MediaPipe version does not provide the Hands API; install the supported vision dependencies."
            )
        if self._hands is None:
            self._hands = self._mediapipe.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.6,
                min_tracking_confidence=0.6,
            )

    def process_bgr_frame(self, frame: Any) -> Any:
        if self._hands is None:
            raise VisionDependencyUnavailable("MediaPipe hand processing has not started.")
        # OpenCV uses BGR; MediaPipe expects RGB. No frames are stored or uploaded.
        # Mirror the webcam view so a user's rightward hand motion is rightward
        # in the gesture engine and matches the preview shown in the dashboard.
        rgb_frame = frame[:, ::-1, ::-1].copy()
        return self._hands.process(rgb_frame)

    def stop(self) -> None:
        if self._hands is not None:
            self._hands.close()
            self._hands = None
