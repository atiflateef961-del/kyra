from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.actions.permissions import PermissionStore
from app.actions.safety import ActionGuard, ActionSafetyError
from app.computer.controller import ComputerController, ControllerAction, ControllerCommand, ControllerError
from app.auth.firebase import VerifiedIdentity
from app.contracts.models import ActionStatus, Intent, Permission, RiskLevel
from app.core.config import Settings
from app.main import create_app
from tests.test_controller import RecordingExecutor


def _guard(executor: RecordingExecutor | None = None, permissions: PermissionStore | None = None, *, dry_run: bool = True) -> tuple[ActionGuard, RecordingExecutor]:
    recording = executor or RecordingExecutor()
    return ActionGuard(ComputerController(dry_run=dry_run, executor=recording), permissions), recording


def test_low_risk_allowlisted_action_uses_the_controller_in_dry_run() -> None:
    guard, executor = _guard()

    action, result = guard.request("PAUSE")

    assert action is not None
    assert action.risk_level == RiskLevel.LOW
    assert action.requires_confirmation is False
    assert result is not None
    assert result.status == ActionStatus.DRY_RUN
    assert executor.calls == []


def test_client_risk_level_cannot_escalate_or_inject_commands() -> None:
    guard, executor = _guard(dry_run=False)
    dangerous = Intent(name="PAUSE", application=None, confidence=1, risk_level=RiskLevel.HIGH)

    action, result = guard.request_from_intent(dangerous)

    assert action is not None
    assert action.risk_level == RiskLevel.LOW
    assert result is not None
    assert result.status == ActionStatus.SUCCEEDED
    assert executor.calls == [("media", "pause")]


def test_unknown_shell_and_blocked_high_risk_actions_never_reach_the_executor() -> None:
    guard, executor = _guard(dry_run=False)

    with pytest.raises(ActionSafetyError, match="allowlist"):
        guard.request("powershell.exe")
    with pytest.raises(ActionSafetyError, match="not allowed"):
        guard.request("PAUSE", {"command": "shutdown /s"})
    with pytest.raises(ActionSafetyError, match="allowlist"):
        guard.request("OPEN_APPLICATION", {"application": "powershell"})

    action, result = guard.request("SHUTDOWN")

    assert action is not None
    assert action.risk_level == RiskLevel.HIGH
    assert result is not None
    assert result.status == ActionStatus.FAILED
    assert executor.calls == []


def test_confirmation_is_required_when_permission_asks_and_cancel_does_not_execute() -> None:
    permissions = PermissionStore()
    permissions.set(
        Permission(
            permission_id="pause-confirm",
            action_identifier="PAUSE",
            granted=True,
            requires_confirmation=True,
            updated_at=datetime.now(UTC),
        )
    )
    guard, executor = _guard(permissions=permissions, dry_run=False)

    action, result = guard.request("PAUSE")
    assert result is None
    assert action is not None and action.requires_confirmation is True

    cancelled = guard.confirm(action.action_id, approved=False)
    assert cancelled.status == ActionStatus.FAILED
    assert executor.calls == []


def test_confirmation_approve_executes_only_the_pending_allowlisted_action() -> None:
    permissions = PermissionStore()
    permissions.set(
        Permission(
            permission_id="pause-confirm",
            action_identifier="PAUSE",
            granted=True,
            requires_confirmation=True,
            updated_at=datetime.now(UTC),
        )
    )
    guard, executor = _guard(permissions=permissions, dry_run=False)

    action, _ = guard.request("PAUSE")
    assert action is not None
    completed = guard.confirm(action.action_id, approved=True)

    assert completed.status == ActionStatus.SUCCEEDED
    assert executor.calls == [("media", "pause")]
    with pytest.raises(ActionSafetyError, match="waiting for confirmation"):
        guard.confirm(action.action_id, approved=True)


def test_confirmation_is_bound_to_the_requesting_owner() -> None:
    permissions = PermissionStore()
    permissions.set(Permission(
        permission_id="volume-confirm",
        action_identifier="VOLUME_UP",
        granted=True,
        requires_confirmation=True,
        updated_at=datetime.now(UTC),
    ))
    guard, executor = _guard(permissions=permissions, dry_run=False)

    action, _ = guard.request("VOLUME_UP", owner_id="user-a")
    assert action is not None
    with pytest.raises(ActionSafetyError, match="waiting for confirmation"):
        guard.confirm(action.action_id, approved=True, owner_id="user-b")
    assert guard.confirm(action.action_id, approved=True, owner_id="user-a").status == ActionStatus.SUCCEEDED
    assert executor.calls == [("volume", 0.05)]


def test_http_confirmation_cannot_be_approved_by_another_user() -> None:
    permissions = PermissionStore()
    permissions.set(Permission(
        permission_id="volume-confirm",
        action_identifier="VOLUME_UP",
        granted=True,
        requires_confirmation=True,
        updated_at=datetime.now(UTC),
    ))
    executor = RecordingExecutor()
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=False),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
        action_guard=ActionGuard(ComputerController(dry_run=False, executor=executor), permissions),
    )
    client = TestClient(app)
    pending = client.post("/api/commands", headers={"Authorization": "Bearer user-a"}, json={"identifier": "VOLUME_UP"})
    action_id = pending.json()["action"]["action_id"]

    rejected = client.post(
        "/api/actions/confirm",
        headers={"Authorization": "Bearer user-b"},
        json={"action_id": action_id, "approved": True},
    )

    assert rejected.status_code == 404
    assert executor.calls == []
    accepted = client.post(
        "/api/actions/confirm",
        headers={"Authorization": "Bearer user-a"},
        json={"action_id": action_id, "approved": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "succeeded"
    assert executor.calls == [("volume", 0.05)]


def test_granting_a_blocked_action_still_cannot_execute_it() -> None:
    permissions = PermissionStore()
    permissions.set(
        Permission(
            permission_id="shutdown",
            action_identifier="SHUTDOWN",
            granted=True,
            requires_confirmation=False,
            updated_at=datetime.now(UTC),
        )
    )
    guard, executor = _guard(permissions=permissions, dry_run=False)

    _, result = guard.request("SHUTDOWN")

    assert result is not None
    assert result.status == ActionStatus.FAILED
    assert executor.calls == []


def test_permission_store_rejects_unknown_actions_and_normalizes_blocked_grants() -> None:
    permissions = PermissionStore()

    with pytest.raises(ValueError, match="registered actions"):
        permissions.set(
            Permission(
                permission_id="unknown",
                action_identifier="UNKNOWN",
                granted=True,
                requires_confirmation=False,
                updated_at=datetime.now(UTC),
            )
        )

    permissions.set(
        Permission(
            permission_id="shutdown",
            action_identifier="SHUTDOWN",
            granted=True,
            requires_confirmation=True,
            updated_at=datetime.now(UTC),
        )
    )
    normalized = permissions.for_action("SHUTDOWN")
    assert normalized.granted is False
    assert normalized.requires_confirmation is False


def test_command_endpoints_reject_abuse_and_confirm_safe_actions() -> None:
    executor = RecordingExecutor()
    permissions = PermissionStore()
    permissions.set(
        Permission(
            permission_id="pause-confirm",
            action_identifier="VOLUME_UP",
            granted=True,
            requires_confirmation=True,
            updated_at=datetime.now(UTC),
        )
    )
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        action_guard=ActionGuard(ComputerController(dry_run=True, executor=executor), permissions),
    )
    client = TestClient(app)

    denied = client.post("/api/commands", json={"identifier": "SHUTDOWN", "parameters": {}})
    assert denied.status_code == 200
    assert denied.json()["result"]["status"] == "failed"
    assert "powershell" not in denied.text

    injected = client.post("/api/commands", json={"identifier": "PAUSE", "parameters": {"cmd": "rm -rf"}})
    assert injected.status_code == 400
    assert injected.json()["error"]["code"] == "ACTION_NOT_ALLOWED"

    pending = client.post("/api/commands", json={"identifier": "VOLUME_UP", "parameters": {}})
    assert pending.status_code == 200
    assert pending.json()["result"] is None
    action_id = pending.json()["action"]["action_id"]

    confirmed = client.post("/api/actions/confirm", json={"action_id": action_id, "approved": True})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "dry_run"
    assert executor.calls == []


def test_controller_still_rejects_direct_unallowlisted_launch() -> None:
    controller = ComputerController(dry_run=True)
    with pytest.raises(ControllerError, match="allowlist"):
        controller.execute(ControllerCommand(ControllerAction.OPEN_APPLICATION, "x", application="powershell"))
