from __future__ import annotations

from datetime import UTC, datetime

from app.actions.registry import ACTION_REGISTRY, get_definition
from app.contracts.models import Permission, RiskLevel


class PermissionStore:
    """In-memory permission defaults. HIGH blocked actions are never granted here."""

    def __init__(self, overrides: dict[str, Permission] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def list(self) -> list[Permission]:
        permissions: list[Permission] = []
        for identifier in sorted(ACTION_REGISTRY):
            permissions.append(self.for_action(identifier))
        return permissions

    def for_action(self, identifier: str) -> Permission:
        if identifier in self._overrides:
            return self._overrides[identifier]
        definition = get_definition(identifier)
        granted = bool(definition and definition.executable and definition.risk_level == RiskLevel.LOW)
        requires_confirmation = bool(definition and definition.requires_confirmation)
        return Permission(
            permission_id=f"default:{identifier}",
            action_identifier=identifier,
            granted=granted,
            requires_confirmation=requires_confirmation,
            updated_at=datetime.now(UTC),
        )

    def set(self, permission: Permission) -> None:
        definition = get_definition(permission.action_identifier)
        if definition is None:
            raise ValueError("Permissions can only be assigned to registered actions.")
        if permission.granted and not definition.executable:
            permission = permission.model_copy(update={"granted": False, "requires_confirmation": False})
        self._overrides[permission.action_identifier] = permission
