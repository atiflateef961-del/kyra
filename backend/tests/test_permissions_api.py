from fastapi.testclient import TestClient

from app.actions.permissions import PermissionStore
from app.actions.safety import ActionGuard
from app.computer.controller import ComputerController
from app.core.config import Settings
from app.main import create_app


def test_permission_endpoints_expose_real_action_state() -> None:
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        action_guard=ActionGuard(ComputerController(dry_run=True), PermissionStore()),
    )
    client = TestClient(app)

    response = client.get("/api/permissions", headers={"Authorization": "Bearer user-a"})
    assert response.status_code == 200
    payload = response.json()
    assert any(item["action_identifier"] == "PAUSE" for item in payload)
    assert any(item["action_identifier"] == "SHUTDOWN" for item in payload)

    updated = client.put(
        "/api/permissions/PAUSE",
        headers={"Authorization": "Bearer user-a"},
        json={"granted": True, "requires_confirmation": True},
    )
    assert updated.status_code == 200
    assert updated.json()["granted"] is True
    assert updated.json()["requires_confirmation"] is True

    invalid = client.put(
        "/api/permissions/UNKNOWN",
        headers={"Authorization": "Bearer user-a"},
        json={"granted": True, "requires_confirmation": False},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_PERMISSION"
