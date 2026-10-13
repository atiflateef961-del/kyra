from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from app.ai.groq import MAX_TRANSCRIPT_CHARS, SYSTEM_PROMPT

Transport = Callable[[str, dict[str, str], bytes, float], str]

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2"


class LocalReasoningUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Local reasoning is unavailable.")


def _default_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ValueError) as cause:
        raise LocalReasoningUnavailable() from cause


class OllamaReasoningProvider:
    """Optional local Ollama JSON completer. It is never required for basic intents."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 8.0,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = (base_url or os.getenv("KYRA_LOCAL_AI_URL", DEFAULT_URL)).rstrip("/")
        self._model = (model or os.getenv("KYRA_LOCAL_AI_MODEL", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        self._timeout = timeout_seconds
        self._transport = transport or _default_transport

    @property
    def name(self) -> str:
        return "local"

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def complete(self, transcript: str) -> dict[str, Any] | None:
        clipped = " ".join(transcript.strip().split())[:MAX_TRANSCRIPT_CHARS]
        if not clipped:
            return None
        body = json.dumps(
            {
                "model": self._model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": clipped},
                ],
            }
        ).encode("utf-8")
        raw = self._transport(
            f"{self._base_url}/api/chat",
            {"Content-Type": "application/json"},
            body,
            self._timeout,
        )
        return _parse_ollama(raw)


def _parse_ollama(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
        content = payload["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
