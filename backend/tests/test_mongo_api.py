from fastapi.testclient import TestClient

from app.auth.firebase import VerifiedIdentity
from app.core.config import Settings
from app.database.mongo import UserSettingsRepository
from app.main import create_app
from tests.test_mongo import InMemoryCollection


def _settings() -> Settings:
    return Settings(app_env="development", cors_origins=("http://localhost:3000",), dry_run=True)


def _verifier(token: str) -> VerifiedIdentity:
    return VerifiedIdentity(firebase_uid=token, email=None, name=None)


def test_settings_api_persists_only_for_verified_owner() -> None:
    repository = UserSettingsRepository(InMemoryCollection())  # type: ignore[arg-type]
    client = TestClient(create_app(_settings(), token_verifier=_verifier, settings_repository=repository))

    assert client.get("/api/settings", headers={"Authorization": "Bearer user-a"}).json() == {}
    saved = client.put(
        "/api/settings",
        headers={"Authorization": "Bearer user-a"},
        json={"theme": "dark", "privacy_mode": True},
    )
    assert saved.status_code == 200
    assert saved.json()["firebase_uid"] == "user-a"

    own = client.get("/api/settings", headers={"Authorization": "Bearer user-a"})
    other = client.get("/api/settings", headers={"Authorization": "Bearer user-b"})
    assert own.json()["theme"] == "dark"
    assert other.json() == {}


def test_settings_api_rejects_empty_or_unknown_updates() -> None:
    repository = UserSettingsRepository(InMemoryCollection())  # type: ignore[arg-type]
    client = TestClient(create_app(_settings(), token_verifier=_verifier, settings_repository=repository))

    empty = client.put("/api/settings", headers={"Authorization": "Bearer user-a"}, json={})
    unknown = client.put(
        "/api/settings",
        headers={"Authorization": "Bearer user-a"},
        json={"firebase_uid": "user-b"},
    )

    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "SETTINGS_EMPTY"
    assert unknown.status_code == 422


def test_settings_api_reports_unavailable_persistence() -> None:
    client = TestClient(create_app(_settings(), token_verifier=_verifier))

    response = client.get("/api/settings", headers={"Authorization": "Bearer user-a"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
