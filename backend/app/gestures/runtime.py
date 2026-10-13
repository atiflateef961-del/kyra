from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from app.camera.vision import MediaPipeHandsProcessor
from app.gestures.engine import GestureDetection, GestureEngine, Landmark, hand_from_mediapipe


@dataclass(frozen=True)
class GestureFrameResult:
    detections: tuple[GestureDetection, ...]
    hands: tuple[tuple[Landmark, ...], ...] = ()


class GestureRuntime:
    """Adapts local MediaPipe frames into deterministic gesture detections."""

    def __init__(self, vision: MediaPipeHandsProcessor, engine: GestureEngine) -> None:
        self._vision = vision
        self._engine = engine

    def start(self) -> None:
        self._engine.reset()
        self._vision.start()

    def stop(self) -> None:
        self._vision.stop()
        self._engine.reset()

    def process_frame(self, frame: Any, timestamp: float | None = None) -> GestureFrameResult:
        result = self._vision.process_bgr_frame(frame)
        detections: list[GestureDetection] = []
        hands: list[tuple[Landmark, ...]] = []
        action_hand = None
        frame_time = monotonic() if timestamp is None else timestamp
        for landmarks in getattr(result, "multi_hand_landmarks", None) or ():
            hand = hand_from_mediapipe(landmarks)
            if action_hand is None:
                action_hand = hand
            hands.append(hand.points)
        if action_hand is not None:
            # Match the dashboard's prior recognition behavior: track one hand
            # for actions while still returning every hand for visualization.
            detection = self._engine.process(action_hand, frame_time)
            if detection is not None:
                detections.append(detection)
        return GestureFrameResult(tuple(detections), tuple(hands))
