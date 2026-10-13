from fastapi.testclient import TestClient
import pytest

from app.core.config import ConfigurationError, Settings
from app.main import create_app


def test_health_reports_safe_local_status() -> None:
    client = TestClient(create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True)))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["api"] == "online"
    assert response.json()["dry_run"] is True
    assert response.json()["ai"]["deterministic"] is True
    assert response.json()["ai"]["cloud_enabled"] is False
    components = response.json()["components"]
    assert components["camera"]["available"] is None
    assert components["camera"]["active"] is False
    assert isinstance(components["vision"]["available"], bool)
    assert components["microphone"]["available"] is None
    assert isinstance(components["speech_to_text"]["available"], bool)
    assert components["speech_to_text"]["model_loaded"] is False
    assert "loads after the first audio" in components["speech_to_text"]["message"]
    assert "GROQ_API_KEY" not in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(self)"


def test_health_reports_missing_local_speech_dependency() -> None:
    class MissingSpeechProvider:
        available = False

        def transcribe(self, audio: object):
            raise AssertionError("Unavailable speech provider must not transcribe")

    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        speech_provider=MissingSpeechProvider(),
    )

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["components"]["speech_to_text"] == {
        "available": False,
        "model_loaded": False,
        "message": "Faster Whisper is unavailable; install the backend voice dependencies.",
    }


def test_cors_rejects_unconfigured_origins() -> None:
    client = TestClient(create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True)))

    response = client.options(
        "/api/health",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400


def test_settings_defaults_to_vite_frontend_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)

    settings = Settings.from_environment()

    assert settings.cors_origins == ("http://localhost:5173", "http://localhost:5174")
    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 8000


def test_settings_reads_canonical_app_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "8123")

    settings = Settings.from_environment()

    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8123


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_settings_rejects_invalid_app_port(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("APP_PORT", port)

    with pytest.raises(ConfigurationError):
        Settings.from_environment()


@pytest.mark.parametrize("origin", ["*", "localhost:3000", "http://localhost:3000/path", "ftp://localhost:3000"])
def test_settings_rejects_invalid_frontend_origins(origin: str) -> None:
    with pytest.raises(ConfigurationError):
        Settings(app_env="test", cors_origins=(origin,), dry_run=True)
