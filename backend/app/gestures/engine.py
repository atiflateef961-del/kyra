from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class GestureName(StrEnum):
    SWIPE_RIGHT = "SWIPE_RIGHT"
    SWIPE_LEFT = "SWIPE_LEFT"
    OPEN_PALM = "OPEN_PALM"
    FIST = "FIST"
    THUMBS_UP = "THUMBS_UP"
    THUMBS_DOWN = "THUMBS_DOWN"
    INDEX_UP = "INDEX_UP"
    INDEX_DOWN = "INDEX_DOWN"
    TWO_FINGERS = "TWO_FINGERS"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    SCROLL = "SCROLL"


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float


@dataclass(frozen=True)
class HandLandmarks:
    points: tuple[Landmark, ...]

    def __post_init__(self) -> None:
        if len(self.points) != 21:
            raise ValueError("A hand requires exactly 21 MediaPipe-compatible landmarks.")


@dataclass(frozen=True)
class GestureDetection:
    gesture: GestureName
    confidence: float
    direction: Literal["up", "down"] | None = None


class GestureEngine:
    """Rule-based gesture recognition; it never maps gestures to computer actions."""

    def __init__(self, movement_threshold: float = 0.10, cooldown_seconds: float = 0.35, static_frames: int = 3) -> None:
        if movement_threshold <= 0 or cooldown_seconds < 0 or static_frames < 1:
            raise ValueError("Gesture thresholds must be positive.")
        self._movement_threshold = movement_threshold
        self._cooldown_seconds = cooldown_seconds
        self._static_frames = static_frames
        self._history: deque[tuple[float, Landmark, Landmark]] = deque(maxlen=12)
        self._last_emitted_at = float("-inf")
        self._pending_static: GestureName | None = None
        self._pending_static_frames = 0
        self._armed = True
        self._neutral_frames = 0
        self._last_emitted_gesture: GestureName | None = None

    def process(self, hand: HandLandmarks, timestamp: float) -> GestureDetection | None:
        """Return at most one local recognition for a frame; callers own event publishing."""
        wrist, index_tip = hand.points[0], hand.points[8]
        self._history.append((timestamp, wrist, index_tip))
        while self._history and timestamp - self._history[0][0] > 0.8:
            self._history.popleft()

        candidate = self._movement_candidate(hand)
        if candidate is None:
            static = self._static_candidate(hand)
            if static is None:
                self._pending_static = None
                self._pending_static_frames = 0
                self._neutral_frames += 1
                if self._neutral_frames >= 3:
                    self._armed = True
                return None
            gesture, confidence = static
            self._neutral_frames = 0
            if gesture == self._pending_static:
                self._pending_static_frames += 1
            else:
                self._pending_static = gesture
                self._pending_static_frames = 1
            if self._pending_static_frames < self._static_frames:
                return None
            direction = None
        else:
            gesture, confidence, direction = candidate
            self._pending_static = None
            self._pending_static_frames = 0
            self._neutral_frames = 0

        changed_gesture = gesture != self._last_emitted_gesture
        if (not self._armed and not changed_gesture) or timestamp - self._last_emitted_at < self._cooldown_seconds:
            return None
        self._last_emitted_at = timestamp
        self._armed = False
        self._last_emitted_gesture = gesture
        self._history.clear()
        self._history.append((timestamp, wrist, index_tip))
        return GestureDetection(gesture=gesture, confidence=confidence, direction=direction)

    def reset(self) -> None:
        """Clear temporal tracking when a camera session ends or restarts."""
        self._history.clear()
        self._last_emitted_at = float("-inf")
        self._pending_static = None
        self._pending_static_frames = 0
        self._armed = True
        self._neutral_frames = 0
        self._last_emitted_gesture = None

    def _movement_candidate(self, hand: HandLandmarks) -> tuple[GestureName, float, Literal["up", "down"] | None] | None:
        if len(self._history) < 2:
            return None
        _, first_wrist, first_index = self._history[0]
        _, last_wrist, last_index = self._history[-1]
        # The camera preview is mirrored for the user, while MediaPipe receives
        # the original frame. Invert X so swipe names match the visible motion.
        horizontal = first_wrist.x - last_wrist.x
        vertical = last_index.y - first_index.y
        if abs(horizontal) >= self._movement_threshold:
            gesture = GestureName.SWIPE_RIGHT if horizontal > 0 else GestureName.SWIPE_LEFT
            return gesture, self._movement_confidence(abs(horizontal)), None
        if self._two_fingers(hand) and abs(vertical) >= self._movement_threshold:
            direction = "up" if vertical < 0 else "down"
            return GestureName.SCROLL, self._movement_confidence(abs(vertical)), direction
        if self._index_only(hand) and abs(vertical) >= self._movement_threshold:
            gesture = GestureName.VOLUME_UP if vertical < 0 else GestureName.VOLUME_DOWN
            return gesture, self._movement_confidence(abs(vertical)), None
        return None

    def _static_candidate(self, hand: HandLandmarks) -> tuple[GestureName, float] | None:
        index, middle, ring, pinky = self._finger_states(hand)
        fingers_closed = not any((index, middle, ring, pinky))
        thumb_tip = hand.points[4]
        index_base = hand.points[5]
        wrist = hand.points[0]
        middle_base = hand.points[9]
        palm_length = self._distance(wrist, middle_base)
        thumb_folded = self._distance(thumb_tip, index_base) <= palm_length * 0.45
        if fingers_closed and thumb_folded:
            return GestureName.FIST, 0.82

        thumb_up = hand.points[4].y < hand.points[3].y
        thumb_down = hand.points[4].y > hand.points[3].y
        thumb_spread = self._distance(hand.points[4], hand.points[5]) >= palm_length * 0.3
        if thumb_up and not any((index, middle, ring, pinky)):
            return GestureName.THUMBS_UP, 0.8
        if thumb_down and not any((index, middle, ring, pinky)):
            return GestureName.THUMBS_DOWN, 0.8
        if all((index, middle, ring, pinky)) and thumb_spread:
            return GestureName.OPEN_PALM, 0.8
        if self._two_fingers(hand):
            return GestureName.TWO_FINGERS, 0.75
        return None

    @staticmethod
    def _distance(first: Landmark, second: Landmark) -> float:
        return ((first.x - second.x) ** 2 + (first.y - second.y) ** 2) ** 0.5

    def _index_only(self, hand: HandLandmarks) -> bool:
        index, middle, ring, pinky = self._finger_states(hand)
        return index and not any((middle, ring, pinky))

    def _two_fingers(self, hand: HandLandmarks) -> bool:
        index, middle, ring, pinky = self._finger_states(hand)
        return index and middle and not ring and not pinky

    @staticmethod
    def _finger_states(hand: HandLandmarks) -> tuple[bool, bool, bool, bool]:
        points = hand.points
        # In image coordinates, a raised finger tip has a smaller Y than its PIP joint.
        return (
            points[8].y < points[6].y,
            points[12].y < points[10].y,
            points[16].y < points[14].y,
            points[20].y < points[18].y,
        )

    def _movement_confidence(self, distance: float) -> float:
        # A transparent deterministic score: threshold crossing is 0.7, capped at 1.
        return min(1.0, 0.7 + 0.3 * ((distance - self._movement_threshold) / self._movement_threshold))


def hand_from_mediapipe(landmarks: Any) -> HandLandmarks:
    """Adapt MediaPipe landmarks without importing MediaPipe into this engine."""
    return HandLandmarks(tuple(Landmark(point.x, point.y) for point in landmarks.landmark))
