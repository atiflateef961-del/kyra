import json

import pytest
from fastapi.testclient import TestClient

from app.ai.groq import GroqReasoningProvider, GroqUnavailable
from app.core.config import Settings
from app.intents.engine import IntentEngine, IntentResolveRequest
from app.intents.registry import validate_intent
from app.main import create_app


class RecordingProvider:
    def __init__(self, payload: dict[str, object] | None = None, *, available: bool = True) -> None:
        self.payload = payload
        self.available = available
        self.name = "groq"
        self.transcripts: list[str] = []

    def complete(self, transcript: str) -> dict[str, object] | None:
        self.transcripts.append(transcript)
        return self.payload


def test_known_voice_and_gestures_stay_deterministic() -> None:
    provider = RecordingProvider({"intent": "PAUSE", "application": None})
    engine = IntentEngine(cloud_provider=provider, cloud_enabled=True)

    voice = engine.resolve_voice("Open the next video.")
    gesture = engine.resolve_gesture("SWIPE_RIGHT")

    assert voice.provider == "deterministic"
    assert voice.intent is not None and voice.intent.name == "NEXT_YOUTUBE_VIDEO"
    assert gesture is not None and gesture.name == "PREVIOUS_MEDIA"
    assert provider.transcripts == []


def test_unmatched_language_does_not_call_cloud_when_disabled() -> None:
    provider = RecordingProvider({"intent": "PAUSE", "application": None})
    engine = IntentEngine(cloud_provider=provider, cloud_enabled=False)

    resolved = engine.resolve_voice("please pause the video for me")

    assert resolved.intent is None
    assert provider.transcripts == []


def test_local_reasoning_is_preferred_over_cloud_and_invalid_local_falls_through() -> None:
    local = RecordingProvider({"intent": "SHUTDOWN", "application": None})
    cloud = RecordingProvider({"intent": "PLAY", "application": None})
    engine = IntentEngine(
        local_provider=local,
        cloud_provider=cloud,
        local_enabled=True,
        cloud_enabled=True,
    )

    resolved = engine.resolve_voice("please play the video")

    assert resolved.provider == "groq"
    assert resolved.intent is not None and resolved.intent.name == "PLAY"
    assert local.transcripts == ["please play the video"]
    assert cloud.transcripts == ["please play the video"]


def test_optional_reasoning_is_validated_against_the_allowlist() -> None:
    provider = RecordingProvider({"intent": "OPEN_APPLICATION", "application": "chrome"})
    engine = IntentEngine(cloud_provider=provider, cloud_enabled=True)

    resolved = engine.resolve_voice("could you start chrome")

    assert resolved.provider == "groq"
    assert resolved.intent is not None
    assert resolved.intent.name == "OPEN_APPLICATION"
    assert resolved.intent.application == "chrome"
    assert resolved.intent.confidence == 0.7


@pytest.mark.parametrize(
    ("transcript", "intent_name"),
    (
        ("turn the volume down just a little", "VOLUME_DOWN"),
        ("show me the next recommended video", "NEXT_YOUTUBE_VIDEO"),
        ("pause this", "PAUSE"),
    ),
)
def test_groq_natural_language_resolves_to_a_validated_action(transcript: str, intent_name: str) -> None:
    provider = RecordingProvider({"intent": intent_name, "application": None})
    engine = IntentEngine(cloud_provider=provider, cloud_enabled=True)

    resolved = engine.resolve_voice(transcript)

    assert resolved.provider == "groq"
    assert resolved.intent is not None and resolved.intent.name == intent_name
    assert provider.transcripts == [transcript]


def test_reasoning_cannot_invent_shell_or_dangerous_intents() -> None:
    engine = IntentEngine(
        cloud_provider=RecordingProvider({"intent": "powershell.exe -Command shutdown", "application": None}),
        cloud_enabled=True,
    )

    assert engine.resolve_voice("run a shell command").intent is None
    assert validate_intent("DELETE_FILE", None) is None
    assert validate_intent("OPEN_APPLICATION", "powershell") is None
    assert validate_intent("PAUSE", "chrome") is None


def test_reasoning_output_requires_exact_schema_before_allowlist_validation() -> None:
    malformed = (
        {"intent": "PAUSE"},
        {"intent": "PAUSE", "application": None, "command": "shutdown"},
        {"intent": 7, "application": None},
        {"intent": None, "application": None, "executable": "powershell"},
    )

    for payload in malformed:
        engine = IntentEngine(cloud_provider=RecordingProvider(payload), cloud_enabled=True)
        assert engine.resolve_voice("could you pause the current media").intent is None


def test_groq_transport_never_includes_the_key_in_errors() -> None:
    def failing_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
        raise GroqUnavailable()

    provider = GroqReasoningProvider(api_key="secret-test-key", transport=failing_transport)

    assert provider.available is True
    try:
        provider.complete("pause")
    except GroqUnavailable as cause:
        assert "secret-test-key" not in str(cause)
    else:
        raise AssertionError("Groq transport failures must be reported as GroqUnavailable.")


def test_groq_parses_structured_json_from_an_injected_transport() -> None:
    completion = {
        "choices": [{"message": {"content": json.dumps({"intent": "PAUSE", "application": None})}}]
    }

    def fake_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
        assert "Authorization" in headers
        assert "secret-test-key" not in url
        return json.dumps(completion)

    provider = GroqReasoningProvider(api_key="secret-test-key", transport=fake_transport)
    assert provider.complete("pause this") == {"intent": "PAUSE", "application": None}


def test_groq_uses_the_configured_gpt_oss_model_by_default() -> None:
    request_body: dict[str, object] = {}

    def fake_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
        request_body.update(json.loads(body))
        return json.dumps({"choices": [{"message": {"content": '{"intent": null, "application": null}'}}]})

    provider = GroqReasoningProvider(api_key="secret-test-key", transport=fake_transport)

    provider.complete("unknown request")

    assert request_body["model"] == "openai/gpt-oss-120b"


def test_intent_endpoint_resolves_without_executing() -> None:
    engine = IntentEngine()
    client = TestClient(
        create_app(
            Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
            intent_engine=engine,
        )
    )

    response = client.post("/api/intents/resolve", json={"source": "voice", "transcript": "Pause"})

    assert response.status_code == 200
    assert response.json()["provider"] == "deterministic"
    assert response.json()["intent"]["name"] == "PAUSE"
    assert "action_id" not in response.json()


def test_health_reports_ai_flags_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "should-not-leak")
    client = TestClient(create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True)))

    response = client.get("/api/health")

    assert response.json()["ai"]["deterministic"] is True
    assert response.json()["ai"]["cloud_enabled"] is False
    assert "should-not-leak" not in response.text
    assert "GROQ_API_KEY" not in response.text


@pytest.mark.parametrize(("api_key", "configured"), (("", False), ("   ", False), ("test-key", True)))
def test_health_reports_groq_key_presence_without_exposing_it(monkeypatch, api_key: str, configured: bool) -> None:
    monkeypatch.setenv("GROQ_API_KEY", api_key)
    client = TestClient(create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True)))

    response = client.get("/api/health")

    assert response.json()["configured"]["groq"] is configured
    assert not api_key or api_key not in response.text


def test_resolve_request_rejects_unknown_fields() -> None:
    try:
        IntentResolveRequest.model_validate({"source": "voice", "transcript": "Pause", "command": "rm -rf"})
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown resolve fields must be rejected.")


def test_resolve_request_rejects_ambiguous_or_empty_sources() -> None:
    for request in (
        {"source": "voice", "transcript": " ", "gesture": None},
        {"source": "voice", "transcript": "pause", "gesture": "OPEN_PALM"},
        {"source": "gesture", "gesture": " ", "transcript": None},
        {"source": "gesture", "gesture": "OPEN_PALM", "transcript": "pause"},
    ):
        try:
            IntentResolveRequest.model_validate(request)
        except ValueError:
            continue
        raise AssertionError("Ambiguous intent request must be rejected.")


def test_local_reasoning_provider_can_supply_a_valid_structured_intent() -> None:
    local = RecordingProvider({"intent": "VOLUME_UP", "application": None})
    engine = IntentEngine(local_provider=local, local_enabled=True)

    resolved = engine.resolve_voice("increase the sound a little")

    assert resolved.provider == "local"
    assert resolved.intent is not None and resolved.intent.name == "VOLUME_UP"
