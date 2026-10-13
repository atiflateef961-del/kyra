from __future__ import annotations

import re

from app.contracts.models import Intent, RiskLevel

ALLOWED_INTENTS = frozenset(
    {
        "PLAY",
        "PAUSE",
        "NEXT_MEDIA",
        "PREVIOUS_MEDIA",
        "NEXT_YOUTUBE_VIDEO",
        "PREVIOUS_YOUTUBE_VIDEO",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "SCROLL_UP",
        "SCROLL_DOWN",
        "GO_BACK",
        "GO_FORWARD",
        "NEXT_SLIDE",
        "PREVIOUS_SLIDE",
        "OPEN_APPLICATION",
    }
)

ALLOWED_APPLICATIONS = frozenset({"chrome", "powerpoint"})

INTENT_ALIASES = {
    "NEXT_VIDEO": "NEXT_MEDIA",
    "PREVIOUS_VIDEO": "PREVIOUS_MEDIA",
    "OPEN_CHROME": "OPEN_APPLICATION",
    "OPEN_POWERPOINT": "OPEN_APPLICATION",
}

ALIAS_APPLICATIONS = {
    "OPEN_CHROME": "chrome",
    "OPEN_POWERPOINT": "powerpoint",
}

_INTENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,47}$")


def canonical_intent_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    name = raw.strip().upper().replace(" ", "_")
    if not _INTENT_NAME.fullmatch(name):
        return None
    return INTENT_ALIASES.get(name, name)


def validate_intent(
    name: str | None,
    application: str | None,
    *,
    confidence: float = 1.0,
) -> Intent | None:
    """Accept only allowlisted structured intents. Never treat text as a command."""
    canonical = canonical_intent_name(name)
    if canonical is None or canonical not in ALLOWED_INTENTS:
        return None

    mapped_application = ALIAS_APPLICATIONS.get((name or "").strip().upper().replace(" ", "_"), application)
    if mapped_application is not None:
        mapped_application = mapped_application.strip().casefold() or None

    if canonical == "OPEN_APPLICATION":
        if mapped_application not in ALLOWED_APPLICATIONS:
            return None
    elif mapped_application is not None:
        return None

    return Intent(
        name=canonical,
        application=mapped_application,
        confidence=min(1.0, max(0.0, confidence)),
        risk_level=RiskLevel.LOW,
    )
