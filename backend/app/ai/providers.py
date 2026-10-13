from __future__ import annotations

from typing import Any, Protocol


class ReasoningProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def available(self) -> bool: ...

    def complete(self, transcript: str) -> dict[str, Any] | None: ...
