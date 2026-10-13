from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, model_validator

from app.ai.providers import ReasoningProvider
from app.contracts.models import Intent
from app.intents.gestures import GestureIntentResolver
from app.intents.registry import validate_intent
from app.intents.voice import VoiceIntentResolver
from app.voice.speech import Transcript, VoiceCommandParser

ThinkingHandler = Callable[[], None]
logger = logging.getLogger("kyra.intent")


class IntentResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["voice", "gesture"]
    transcript: str | None = None
    gesture: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def require_source_payload(self) -> "IntentResolveRequest":
        if self.source == "voice":
            if not self.transcript or not self.transcript.strip() or self.gesture is not None:
                raise ValueError("Voice intent requests require only a non-empty transcript.")
        elif not self.gesture or not self.gesture.strip() or self.transcript is not None:
            raise ValueError("Gesture intent requests require only a gesture.")
        return self


class IntentResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent | None
    provider: str | None


class StructuredReasoningIntent(BaseModel):
    """Exact machine-readable shape accepted from optional reasoning providers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: StrictStr | None
    application: StrictStr | None


class IntentEngine:
    """Two-layer intent resolver: deterministic first, optional reasoning second.

    Layer 2 is used only for unmatched natural-language transcripts. Gestures and
    known commands never call a remote or local LLM. Resolved intents are never
    executed by this engine.
    """

    def __init__(
        self,
        *,
        parser: VoiceCommandParser | None = None,
        voice_resolver: VoiceIntentResolver | None = None,
        gesture_resolver: GestureIntentResolver | None = None,
        local_provider: ReasoningProvider | None = None,
        cloud_provider: ReasoningProvider | None = None,
        local_enabled: bool = False,
        cloud_enabled: bool = False,
        on_thinking: ThinkingHandler | None = None,
    ) -> None:
        self._parser = parser or VoiceCommandParser()
        self._voice_resolver = voice_resolver or VoiceIntentResolver()
        self._gesture_resolver = gesture_resolver or GestureIntentResolver()
        self._local_provider = local_provider
        self._cloud_provider = cloud_provider
        self._local_enabled = local_enabled
        self._cloud_enabled = cloud_enabled
        self._on_thinking = on_thinking

    def resolve(self, request: IntentResolveRequest) -> IntentResolveResponse:
        if request.source == "gesture":
            if not request.gesture:
                return IntentResolveResponse(intent=None, provider=None)
            intent = self.resolve_gesture(request.gesture, request.confidence)
            return IntentResolveResponse(intent=intent, provider="deterministic" if intent else None)
        if not request.transcript:
            return IntentResolveResponse(intent=None, provider=None)
        return self.resolve_voice(request.transcript)

    def resolve_gesture(self, gesture: str, confidence: float = 1.0) -> Intent | None:
        return self._gesture_resolver.resolve(gesture, confidence)

    def resolve_voice(self, transcript: str) -> IntentResolveResponse:
        parsed = self._parser.parse(Transcript(transcript))
        deterministic = self._voice_resolver.resolve(parsed)
        if deterministic is not None:
            return IntentResolveResponse(intent=deterministic, provider="deterministic")

        local = self._reason(self._local_provider, transcript, enabled=self._local_enabled, provider_name="local")
        if local is not None:
            return IntentResolveResponse(intent=local, provider="local")

        cloud = self._reason(self._cloud_provider, transcript, enabled=self._cloud_enabled, provider_name="groq")
        if cloud is not None:
            return IntentResolveResponse(intent=cloud, provider="groq")
        return IntentResolveResponse(intent=None, provider=None)

    def _reason(self, provider: ReasoningProvider | None, transcript: str, *, enabled: bool, provider_name: str) -> Intent | None:
        if not enabled or provider is None or not provider.available:
            return None
        if self._on_thinking is not None:
            self._on_thinking()
        try:
            payload = provider.complete(transcript)
        except Exception as cause:
            logger.error("reasoning_provider_failed provider=%s", provider_name, extra={"error_type": type(cause).__name__})
            return None
        return _intent_from_reasoning(payload)


def _intent_from_reasoning(payload: dict[str, Any] | None) -> Intent | None:
    if not payload:
        return None
    try:
        structured = StructuredReasoningIntent.model_validate(payload)
    except ValidationError:
        return None
    if structured.intent is None:
        return None
    return validate_intent(structured.intent, structured.application, confidence=0.7)
