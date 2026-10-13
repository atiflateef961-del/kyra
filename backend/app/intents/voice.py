from __future__ import annotations

from app.contracts.models import Intent
from app.intents.registry import validate_intent
from app.voice.speech import ParsedVoiceCommand


class VoiceIntentResolver:
    """Maps exact, recognized voice candidates to a small validated intent set.

    This is deliberately a closed mapping: arbitrary transcript text cannot
    become an intent, and an intent cannot execute a computer action on its own.
    """

    _INTENTS: dict[str, tuple[str, str | None]] = {
        "PAUSE": ("PAUSE", None),
        "PLAY": ("PLAY", None),
        "NEXT_VIDEO": ("NEXT_YOUTUBE_VIDEO", None),
        "PREVIOUS_VIDEO": ("PREVIOUS_YOUTUBE_VIDEO", None),
        "VOLUME_UP": ("VOLUME_UP", None),
        "VOLUME_DOWN": ("VOLUME_DOWN", None),
        "SCROLL_DOWN": ("SCROLL_DOWN", None),
        "SCROLL_UP": ("SCROLL_UP", None),
        "OPEN_CHROME": ("OPEN_APPLICATION", "chrome"),
        "OPEN_POWERPOINT": ("OPEN_APPLICATION", "powerpoint"),
        "GO_BACK": ("GO_BACK", None),
    }

    def resolve(self, candidate: ParsedVoiceCommand) -> Intent | None:
        if candidate.command_name is None:
            return None
        mapped = self._INTENTS.get(candidate.command_name)
        if mapped is None:
            return None
        name, application = mapped
        return validate_intent(name, application)
