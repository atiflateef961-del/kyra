from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    ERROR = "error"


class RiskLevel(StrEnum):
    LOW = "low"
    HIGH = "high"


class ActionStatus(StrEnum):
    PLANNED = "planned"
    PENDING_CONFIRMATION = "pending_confirmation"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DRY_RUN = "dry_run"


class AgentStatus(ContractModel):
    state: AgentState
    dry_run: bool
    updated_at: datetime
    message: str | None = None


class CameraStatus(ContractModel):
    available: bool | None
    active: bool
    updated_at: datetime
    message: str | None = None
    diagnostic_code: str = "not_checked"


class MicrophoneStatus(ContractModel):
    available: bool | None
    active: bool
    updated_at: datetime
    message: str | None = None
    diagnostic_code: str = "not_checked"
    diagnostic_detail: str | None = None


class AppContext(ContractModel):
    application: str
    profile: str
    available: bool
    label: str


class GestureEvent(ContractModel):
    event_id: str
    gesture: str
    confidence: float = Field(ge=0, le=1)
    timestamp: datetime
    context: str | None = None


class VoiceEvent(ContractModel):
    event_id: str
    phase: str
    timestamp: datetime
    transcript: str | None = None
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None


class Intent(ContractModel):
    name: str
    application: str | None = None
    confidence: float = Field(ge=0, le=1)
    risk_level: RiskLevel


class Action(ContractModel):
    action_id: str
    identifier: str
    risk_level: RiskLevel
    requires_confirmation: bool
    parameters: dict[str, Any] = Field(default_factory=dict)


class ActionResult(ContractModel):
    action_id: str
    status: ActionStatus
    completed_at: datetime
    message: str | None = None


class ActivityLog(ContractModel):
    activity_id: str
    timestamp: datetime
    input_type: str
    intent_name: str | None = None
    action_id: str | None = None
    result_status: ActionStatus
    risk_level: RiskLevel


class Device(ContractModel):
    device_id: str
    display_name: str
    registered_at: datetime
    last_seen_at: datetime


class Notification(ContractModel):
    notification_id: str
    title: str
    message: str
    severity: Literal["info", "warning", "critical"]
    read: bool = False
    created_at: datetime
    updated_at: datetime


class UserSettings(ContractModel):
    theme: str | None = None
    camera_enabled: bool
    microphone_enabled: bool
    privacy_mode: bool
    ai_provider: str | None = None


class UserSettingsUpdate(ContractModel):
    theme: str | None = None
    camera_enabled: bool | None = None
    microphone_enabled: bool | None = None
    privacy_mode: bool | None = None
    ai_provider: str | None = None


class GestureMapping(ContractModel):
    mapping_id: str
    gesture: str
    action: str
    application: str
    enabled: bool
    updated_at: datetime


class Permission(ContractModel):
    permission_id: str
    action_identifier: str
    granted: bool
    requires_confirmation: bool
    updated_at: datetime


class CommandRequest(ContractModel):
    intent: Intent | None = None
    identifier: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_one_source(self) -> "CommandRequest":
        has_intent = self.intent is not None
        has_identifier = bool(self.identifier and self.identifier.strip())
        if has_intent == has_identifier:
            raise ValueError("Provide exactly one of intent or identifier.")
        return self


class ConfirmRequest(ContractModel):
    action_id: str
    approved: bool


class CommandResponse(ContractModel):
    action: Action | None = None
    result: ActionResult | None = None
