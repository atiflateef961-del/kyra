from __future__ import annotations

from dataclasses import dataclass

from app.context.detect import ForegroundReader, WindowsForegroundReader
from app.context.profiles import classify, gesture_intent_name
from app.contracts.models import AppContext, Intent
from app.intents.registry import validate_intent


@dataclass(frozen=True)
class ContextualGestureIntent:
    context: AppContext
    intent: Intent | None


class ContextEngine:
    """Maps recognized inputs through the currently active local application profile."""

    def __init__(self, reader: ForegroundReader | None = None) -> None:
        self._reader = reader or WindowsForegroundReader()

    def detect(self) -> AppContext:
        return classify(self._reader.read())

    def resolve_gesture(
        self,
        gesture: str,
        confidence: float = 1.0,
        profile_override: str | None = None,
        direction: str | None = None,
    ) -> ContextualGestureIntent:
        context = self.detect()
        if profile_override == "youtube":
            context = context.model_copy(update={
                "profile": "youtube",
                "label": "YouTube (selected target)",
            })
        elif not context.available:
            return ContextualGestureIntent(context=context, intent=None)
        name = gesture_intent_name(gesture, profile_override or context.profile, direction)
        return ContextualGestureIntent(
            context=context,
            intent=validate_intent(name, None, confidence=confidence),
        )
