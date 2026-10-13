from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from app.actions.permissions import PermissionStore
from app.actions.registry import ActionDefinition, get_definition
from app.computer.controller import ALLOWED_APPLICATIONS, ComputerController, ControllerAction, ControllerCommand
from app.contracts.models import Action, ActionResult, ActionStatus, Intent

FORBIDDEN_PARAMETER_KEYS = frozenset(
    {"command", "cmd", "shell", "executable", "path", "script", "powershell", "args", "cwd"}
)
FORBIDDEN_VALUE_MARKERS = (".exe", "powershell", "cmd.exe", "bash", "/", "\\", "..")


class ActionSafetyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ActionGuard:
    """Validates, authorizes, and optionally confirms actions before the controller runs.

    Arbitrary text, unknown identifiers, and blocked high-risk actions never reach
    the Windows executor. Confirmation cannot enable a non-executable action.
    """

    def __init__(
        self,
        controller: ComputerController,
        permissions: PermissionStore | None = None,
    ) -> None:
        self._controller = controller
        self._permissions = permissions or PermissionStore()
        self._pending: dict[str, tuple[Action, str | None]] = {}
        self._pending_lock = Lock()

    def request_from_intent(
        self, intent: Intent, *, owner_id: str | None = None
    ) -> tuple[Action | None, ActionResult | None]:
        parameters: dict[str, Any] = {}
        if intent.name == "OPEN_APPLICATION" and intent.application is not None:
            parameters["application"] = intent.application
        return self.request(intent.name, parameters, owner_id=owner_id)

    def request(
        self,
        identifier: str,
        parameters: dict[str, Any] | None = None,
        *,
        owner_id: str | None = None,
    ) -> tuple[Action | None, ActionResult | None]:
        definition = get_definition(identifier)
        if definition is None:
            raise ActionSafetyError("ACTION_NOT_ALLOWED", "The requested action is not in the allowlist.")
        cleaned = self._validate_parameters(definition, parameters or {})
        action = Action(
            action_id=str(uuid4()),
            identifier=definition.identifier,
            risk_level=definition.risk_level,
            requires_confirmation=False,
            parameters=cleaned,
        )
        permission = self._permissions.for_action(definition.identifier)
        if not permission.granted or not definition.executable:
            return action, self._result(action, ActionStatus.FAILED, "The requested action is not permitted.")

        needs_confirmation = definition.requires_confirmation or permission.requires_confirmation
        action = action.model_copy(update={"requires_confirmation": needs_confirmation})
        if needs_confirmation:
            with self._pending_lock:
                self._pending[action.action_id] = (action, owner_id)
            return action, None
        return action, self._execute(action)

    def confirm(self, action_id: str, approved: bool, *, owner_id: str | None = None) -> ActionResult:
        with self._pending_lock:
            pending = self._pending.get(action_id)
            if pending is None or pending[1] != owner_id:
                raise ActionSafetyError("ACTION_NOT_FOUND", "There is no action waiting for confirmation.")
            action, _ = self._pending.pop(action_id)
        if not approved:
            return self._result(action, ActionStatus.FAILED, "The action was cancelled.")
        definition = get_definition(action.identifier)
        permission = self._permissions.for_action(action.identifier)
        if definition is None or not definition.executable or not permission.granted:
            return self._result(action, ActionStatus.FAILED, "The requested action is not permitted.")
        return self._execute(action)

    def _execute(self, action: Action) -> ActionResult:
        try:
            command = ControllerCommand(
                action=ControllerAction(action.identifier),
                action_id=action.action_id,
                application=action.parameters.get("application") if isinstance(action.parameters.get("application"), str) else None,
            )
        except ValueError as cause:
            raise ActionSafetyError("ACTION_NOT_ALLOWED", "The requested action is not in the allowlist.") from cause
        return self._controller.execute(command)

    @staticmethod
    def _validate_parameters(definition: ActionDefinition, parameters: dict[str, Any]) -> dict[str, Any]:
        unknown = set(parameters) - definition.allowed_parameters
        if unknown & FORBIDDEN_PARAMETER_KEYS or unknown:
            raise ActionSafetyError("ACTION_NOT_ALLOWED", "The requested action parameters are not allowed.")
        cleaned: dict[str, Any] = {}
        for key, value in parameters.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ActionSafetyError("ACTION_NOT_ALLOWED", "The requested action parameters are not allowed.")
            if isinstance(value, str):
                lowered = value.casefold()
                if key == "application":
                    if value not in ALLOWED_APPLICATIONS:
                        raise ActionSafetyError("ACTION_NOT_ALLOWED", "The requested application is not in the allowlist.")
                elif any(marker in lowered for marker in FORBIDDEN_VALUE_MARKERS):
                    raise ActionSafetyError("ACTION_NOT_ALLOWED", "The requested action parameters are not allowed.")
            cleaned[key] = value
        if definition.identifier == "OPEN_APPLICATION" and "application" not in cleaned:
            raise ActionSafetyError("ACTION_NOT_ALLOWED", "OPEN_APPLICATION requires an allowlisted application.")
        return cleaned

    @staticmethod
    def _result(action: Action, status: ActionStatus, message: str) -> ActionResult:
        return ActionResult(
            action_id=action.action_id,
            status=status,
            completed_at=datetime.now(UTC),
            message=message,
        )
