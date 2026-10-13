import re
from pathlib import Path

from app.contracts import models


CONTRACTS = (
    "AgentStatus",
    "CameraStatus",
    "MicrophoneStatus",
    "AppContext",
    "GestureEvent",
    "VoiceEvent",
    "Intent",
    "Action",
    "ActionResult",
    "ActivityLog",
    "Device",
    "UserSettings",
    "UserSettingsUpdate",
    "GestureMapping",
    "Permission",
    "CommandRequest",
    "ConfirmRequest",
    "CommandResponse",
)


def _typescript_fields(source: str, interface_name: str) -> set[str]:
    match = re.search(rf"export interface {interface_name} \{{(?P<body>.*?)\n\}}", source, re.DOTALL)
    assert match, f"Missing TypeScript interface: {interface_name}"
    return set(re.findall(r"^  ([a-z_]+)\??:", match.group("body"), re.MULTILINE))


def test_frontend_and_backend_contract_fields_match() -> None:
    typescript = Path(__file__).parents[2] / "frontend" / "types" / "contracts.ts"
    source = typescript.read_text(encoding="utf-8")

    for name in CONTRACTS:
        backend_fields = set(getattr(models, name).model_fields)
        assert _typescript_fields(source, name) == backend_fields, name


def test_contracts_reject_unknown_fields() -> None:
    invalid_status = {"state": "online", "dry_run": True, "updated_at": "2026-01-01T00:00:00Z", "unexpected": True}

    try:
        models.AgentStatus.model_validate(invalid_status)
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown contract fields must be rejected.")
