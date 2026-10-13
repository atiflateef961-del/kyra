import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import firebase as firebase_auth
from app.auth.firebase import FirebaseConfigurationError, FirebaseVerificationError, InvalidAuthenticationToken, VerifiedIdentity, verify_id_token
from app.core.config import Settings
from app.main import create_app


def _settings() -> Settings:
    return Settings(app_env="development", cors_origins=("http://localhost:3000",), dry_run=True)


def _verifier(token: str) -> VerifiedIdentity:
    if token != "valid-token":
        raise InvalidAuthenticationToken("invalid")
    return VerifiedIdentity(firebase_uid="user-123", email="user@example.com", name="Test User")


def test_health_remains_public_when_authentication_is_enabled() -> None:
    client = TestClient(create_app(_settings(), token_verifier=_verifier))

    response = client.get("/api/health")

    assert response.status_code == 200


def test_websocket_accepts_the_configured_lan_frontend_origin() -> None:
    origin = "https://192.168.1.31:5173"
    settings = Settings(app_env="development", cors_origins=(origin,), dry_run=True)
    client = TestClient(create_app(settings, token_verifier=_verifier))

    with client.websocket_connect(
        "/ws/agent",
        subprotocols=["bearer", "valid-token"],
        headers={"origin": origin},
    ) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}


def test_websocket_rejects_an_unconfigured_lan_origin() -> None:
    settings = Settings(app_env="development", cors_origins=("https://192.168.1.31:5173",), dry_run=True)
    client = TestClient(create_app(settings, token_verifier=_verifier))

    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect(
            "/ws/agent",
            subprotocols=["bearer", "valid-token"],
            headers={"origin": "https://192.168.1.44:5173"},
        ):
            pass

    assert rejected.value.code == 1008


def test_protected_route_requires_a_bearer_token() -> None:
    client = TestClient(create_app(_settings(), token_verifier=_verifier))

    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_protected_route_uses_verified_identity() -> None:
    client = TestClient(create_app(_settings(), token_verifier=_verifier))

    response = client.get("/api/me", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    assert response.json() == {
        "firebase_uid": "user-123",
        "email": "user@example.com",
        "name": "Test User",
    }


def test_invalid_bearer_token_is_rejected() -> None:
    client = TestClient(create_app(_settings(), token_verifier=_verifier))

    response = client.get("/api/me", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_AUTHENTICATION"


def test_websocket_requires_handshake_authentication() -> None:
    client = TestClient(create_app(_settings(), token_verifier=_verifier))

    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect("/ws/agent") as rejected_connection:
            rejected_connection.receive_json()
    assert rejected.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as query_rejected:
        with client.websocket_connect("/ws/agent?access_token=valid-token") as connection:
            connection.receive_json()
    assert query_rejected.value.code == 1008

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "valid-token"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        assert [connection.receive_json()["event_type"] for _ in range(3)] == [
            "agent_status",
            "camera_status",
            "microphone_status",
        ]
        connection.send_json({"type": "ping"})
        assert connection.receive_json() == {"type": "pong"}

    with client.websocket_connect("/ws/agent", headers={"Authorization": "Bearer valid-token"}) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        assert [connection.receive_json()["event_type"] for _ in range(3)] == [
            "agent_status",
            "camera_status",
            "microphone_status",
        ]
        connection.send_json({"type": "ping"})
        assert connection.receive_json() == {"type": "pong"}

    with pytest.raises(WebSocketDisconnect) as invalid:
        with client.websocket_connect("/ws/agent", subprotocols=["bearer", "invalid-token"]) as connection:
            connection.receive_json()
    assert invalid.value.code == 1008


def test_secure_lan_origin_is_allowed_for_api_and_authenticated_websocket() -> None:
    lan_origin = "https://10.23.45.67:5173"
    settings = Settings(app_env="test", cors_origins=(lan_origin,), dry_run=True)
    client = TestClient(create_app(settings, token_verifier=_verifier))

    response = client.get("/api/health", headers={"Origin": lan_origin})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == lan_origin

    with client.websocket_connect(
        "/ws/agent",
        headers={"Origin": lan_origin},
        subprotocols=["bearer", "valid-token"],
    ) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        assert [connection.receive_json()["event_type"] for _ in range(3)] == [
            "agent_status",
            "camera_status",
            "microphone_status",
        ]

def test_websocket_reports_missing_admin_configuration_as_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL", "FIREBASE_PRIVATE_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_app(_settings()))

    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect("/ws/agent", subprotocols=["bearer", "valid-token"]) as connection:
            connection.receive_json()

    assert rejected.value.code == 1011


def test_firebase_verification_service_failure_is_not_reported_as_bad_credentials() -> None:
    def fail_verification(token: str) -> VerifiedIdentity:
        raise FirebaseVerificationError("CertificateFetchError")

    client = TestClient(create_app(_settings(), token_verifier=fail_verification))

    response = client.get("/api/me", headers={"Authorization": "Bearer firebase-token"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTHENTICATION_UNAVAILABLE"

    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect("/ws/agent", subprotocols=["bearer", "firebase-token"]) as connection:
            connection.receive_json()
    assert rejected.value.code == 1011


def test_verify_id_token_rejects_empty_tokens() -> None:
    with pytest.raises(InvalidAuthenticationToken):
        verify_id_token(" ")


def test_verify_id_token_returns_only_verified_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeAuth:
        def verify_id_token(self, token: str, *, check_revoked: bool) -> dict[str, str]:
            calls["token"] = token
            calls["check_revoked"] = check_revoked
            return {"uid": "verified-user", "email": "verified@example.com", "name": "Verified User", "extra": "ignored"}

    monkeypatch.setattr(firebase_auth, "_firebase_admin_auth", lambda: FakeAuth())

    assert verify_id_token("firebase-token") == VerifiedIdentity(
        firebase_uid="verified-user",
        email="verified@example.com",
        name="Verified User",
    )
    assert calls == {"token": "firebase-token", "check_revoked": True}


def test_verify_id_token_surfaces_missing_admin_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firebase_auth, "_firebase_admin_auth", lambda: (_ for _ in ()).throw(FirebaseConfigurationError("missing")))

    with pytest.raises(FirebaseConfigurationError):
        verify_id_token("firebase-token")


def test_verify_id_token_distinguishes_invalid_credentials_from_admin_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeInvalidToken(Exception):
        pass

    class FakeAuth:
        InvalidIdTokenError = FakeInvalidToken
        UserDisabledError = FakeInvalidToken
        UserNotFoundError = FakeInvalidToken

        def __init__(self, error: Exception) -> None:
            self.error = error

        def verify_id_token(self, token: str, *, check_revoked: bool) -> dict[str, str]:
            raise self.error

    monkeypatch.setattr(firebase_auth, "_firebase_admin_auth", lambda: FakeAuth(FakeInvalidToken()))
    with pytest.raises(InvalidAuthenticationToken):
        verify_id_token("firebase-token")

    monkeypatch.setattr(firebase_auth, "_firebase_admin_auth", lambda: FakeAuth(TimeoutError()))
    with pytest.raises(FirebaseVerificationError) as failure:
        verify_id_token("firebase-token")
    assert failure.value.error_type == "TimeoutError"
