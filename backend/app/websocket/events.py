from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import logging
from typing import TypeAlias

from fastapi import WebSocket
from pydantic import Field

from app.contracts.models import (
    Action,
    ActionResult,
    AgentStatus,
    CameraStatus,
    ContractModel,
    GestureEvent,
    Intent,
    MicrophoneStatus,
    VoiceEvent,
)

logger = logging.getLogger("kyra.websocket")


class AgentEventType(StrEnum):
    AGENT_STATUS = "agent_status"
    CAMERA_STATUS = "camera_status"
    MICROPHONE_STATUS = "microphone_status"
    GESTURE_DETECTED = "gesture_detected"
    VOICE_STARTED = "voice_started"
    VOICE_TRANSCRIPT = "voice_transcript"
    INTENT_DETECTED = "intent_detected"
    AI_THINKING = "ai_thinking"
    ACTION_REQUESTED = "action_requested"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ACTION_EXECUTING = "action_executing"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"


EventPayload: TypeAlias = AgentStatus | CameraStatus | MicrophoneStatus | GestureEvent | VoiceEvent | Intent | Action | ActionResult

PAYLOAD_MODELS: dict[AgentEventType, type[ContractModel]] = {
    AgentEventType.AGENT_STATUS: AgentStatus,
    AgentEventType.CAMERA_STATUS: CameraStatus,
    AgentEventType.MICROPHONE_STATUS: MicrophoneStatus,
    AgentEventType.GESTURE_DETECTED: GestureEvent,
    AgentEventType.VOICE_STARTED: VoiceEvent,
    AgentEventType.VOICE_TRANSCRIPT: VoiceEvent,
    AgentEventType.INTENT_DETECTED: Intent,
    AgentEventType.AI_THINKING: AgentStatus,
    AgentEventType.ACTION_REQUESTED: Action,
    AgentEventType.CONFIRMATION_REQUIRED: Action,
    AgentEventType.ACTION_EXECUTING: Action,
    AgentEventType.ACTION_COMPLETED: ActionResult,
    AgentEventType.ACTION_FAILED: ActionResult,
}


class AgentEvent(ContractModel):
    event_type: AgentEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, object]


class AgentEventHub:
    """Connection manager for schema-validated, owner-scoped events."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._owners: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, owner_id: str = "default", *, accept: bool = True) -> None:
        if accept:
            await websocket.accept()
        owner = owner_id.strip() or "default"
        self._connections.setdefault(owner, set()).add(websocket)
        self._owners[websocket] = owner

    def disconnect(self, websocket: WebSocket) -> None:
        owner = self._owners.pop(websocket, None)
        if owner is None:
            return
        connections = self._connections.get(owner)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(owner, None)

    async def publish(self, event_type: AgentEventType, payload: EventPayload, owner_id: str | None = None) -> None:
        expected = PAYLOAD_MODELS[event_type]
        if not isinstance(payload, expected):
            raise TypeError(f"{event_type.value} requires {expected.__name__} payload.")

        event = AgentEvent(event_type=event_type, payload=payload.model_dump(mode="json"))
        if owner_id is None:
            connections = {connection for group in self._connections.values() for connection in group}
        else:
            connections = set(self._connections.get(owner_id.strip() or "default", set()))
        stale: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(event.model_dump(mode="json"))
            except Exception as cause:
                logger.warning("websocket_event_delivery_failed", extra={"error_type": type(cause).__name__})
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)
