from app.contracts.models import RiskLevel
from app.intents.gestures import GestureIntentResolver
from app.intents.voice import VoiceIntentResolver
from app.voice.speech import ParsedVoiceCommand


def test_recognized_voice_candidate_becomes_a_closed_low_risk_intent() -> None:
    intent = VoiceIntentResolver().resolve(ParsedVoiceCommand("Open Chrome", "OPEN_CHROME"))

    assert intent is not None
    assert intent.name == "OPEN_APPLICATION"
    assert intent.application == "chrome"
    assert intent.confidence == 1.0
    assert intent.risk_level == RiskLevel.LOW


def test_unrecognized_or_unmapped_candidates_never_become_intents() -> None:
    resolver = VoiceIntentResolver()

    assert resolver.resolve(ParsedVoiceCommand("run a shell command", None)) is None
    assert resolver.resolve(ParsedVoiceCommand("unknown", "DELETE_EVERYTHING")) is None


def test_required_gesture_mappings_resolve() -> None:
    resolver = GestureIntentResolver()
    expected = {
        "THUMBS_UP": "VOLUME_UP",
        "THUMBS_DOWN": "VOLUME_DOWN",
        "INDEX_UP": "VOLUME_UP",
        "INDEX_DOWN": "VOLUME_DOWN",
        "SWIPE_LEFT": "NEXT_MEDIA",
        "SWIPE_RIGHT": "PREVIOUS_MEDIA",
        "OPEN_PALM": "PAUSE",
        "FIST": "PLAY",
        "TWO_FINGERS": "SCROLL_DOWN",
    }

    assert {gesture: resolver.resolve(gesture).name for gesture in expected} == expected
