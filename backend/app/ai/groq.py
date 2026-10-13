from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

Transport = Callable[[str, dict[str, str], bytes, float], str]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_TRANSCRIPT_CHARS = 500

SYSTEM_PROMPT = (
    "Map a spoken computer-control request to one allowed intent. "
    "Understand English, Urdu, and Roman Urdu, including mixed-language requests. "
    "If the transcript is unclear or refers to an unknown target, return a null intent. "
    'Return exactly this JSON shape and no other fields: {"intent": "NAME", "application": null}. '
    "The intent may be null. Set application to chrome or powerpoint only for OPEN_APPLICATION; otherwise set it to null. "
    "Allowed intents: PLAY, PAUSE, NEXT_MEDIA, PREVIOUS_MEDIA, NEXT_YOUTUBE_VIDEO, "
    "PREVIOUS_YOUTUBE_VIDEO, VOLUME_UP, "
    "VOLUME_DOWN, SCROLL_UP, SCROLL_DOWN, GO_BACK, GO_FORWARD, OPEN_APPLICATION. "
    "For OPEN_APPLICATION, application must be chrome or powerpoint. "
    "Use the YouTube intents for requests about video navigation; use NEXT_MEDIA or "
    "PREVIOUS_MEDIA only for generic media tracks. Never invent other intents. "
    "Never return shell commands, paths, or executables. "
    'If the request is not one of these, return {"intent": null, "application": null}.'
)


class GroqUnavailable(RuntimeError):
    """Raised without request headers or secret material."""

    def __init__(self) -> None:
        super().__init__("Cloud reasoning is unavailable.")


def _default_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ValueError) as cause:
        raise GroqUnavailable() from cause


class GroqReasoningProvider:
    """Optional Groq JSON completer. It never executes computer actions."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 8.0,
        transport: Transport | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")).strip() or None
        self._model = (model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        self._timeout = timeout_seconds
        self._transport = transport or _default_transport

    @property
    def name(self) -> str:
        return "groq"

    @property
    def available(self) -> bool:
        return self._api_key is not None

    def complete(self, transcript: str) -> dict[str, Any] | None:
        if not self.available:
            raise GroqUnavailable()
        clipped = " ".join(transcript.strip().split())[:MAX_TRANSCRIPT_CHARS]
        if not clipped:
            return None

        body = json.dumps(
            {
                "model": self._model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": clipped},
                ],
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        raw = self._transport(GROQ_URL, headers, body, self._timeout)
        return _parse_completion(raw)


def _parse_completion(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
