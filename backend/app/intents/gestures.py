from __future__ import annotations

from app.contracts.models import Intent
from app.gestures.engine import GestureName
from app.intents.registry import validate_intent


class GestureIntentResolver:
    """Maps recognized gesture names to generic intents without executing them.

    Application-specific meaning is owned by a later context engine.
    """

    _INTENTS: dict[str, str] = {
        GestureName.SWIPE_LEFT.value: "NEXT_MEDIA",
        GestureName.SWIPE_RIGHT.value: "PREVIOUS_MEDIA",
        GestureName.OPEN_PALM.value: "PAUSE",
        GestureName.FIST.value: "PLAY",
        GestureName.THUMBS_UP.value: "VOLUME_UP",
        GestureName.THUMBS_DOWN.value: "VOLUME_DOWN",
        GestureName.INDEX_UP.value: "VOLUME_UP",
        GestureName.INDEX_DOWN.value: "VOLUME_DOWN",
        GestureName.TWO_FINGERS.value: "SCROLL_DOWN",
        GestureName.VOLUME_UP.value: "VOLUME_UP",
        GestureName.VOLUME_DOWN.value: "VOLUME_DOWN",
        GestureName.SCROLL.value: "SCROLL_DOWN",
    }

    def resolve(self, gesture: str, confidence: float = 1.0) -> Intent | None:
        mapped = self._INTENTS.get(gesture.strip().upper())
        if mapped is None:
            return None
        return validate_intent(mapped, None, confidence=confidence)
