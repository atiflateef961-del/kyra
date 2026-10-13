from __future__ import annotations

import asyncio
import base64
import binascii
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo.errors import DuplicateKeyError
from fastapi.responses import JSONResponse

from app.actions.permissions import PermissionStore
from app.actions.registry import get_definition
from app.actions.safety import ActionGuard, ActionSafetyError
from app.auth.firebase import FirebaseConfigurationError, FirebaseVerificationError, InvalidAuthenticationToken, VerifiedIdentity, verify_id_token
from app.ai.groq import GroqReasoningProvider
from app.ai.local import OllamaReasoningProvider
from app.camera.service import CameraService, CameraUnavailable
from app.camera.vision import MediaPipeHandsProcessor, VisionDependencyUnavailable
from app.camera.worker import CameraWorker
from app.computer.controller import ComputerController
from app.context.engine import ContextEngine
from app.contracts.models import ActionStatus, ActivityLog, AgentState, AgentStatus, CommandRequest, ConfirmRequest, Device, GestureEvent, GestureMapping, Notification, UserSettingsUpdate
from app.core.config import Settings
from app.core.logging import configure_logging
from app.database.mongo import ActivityLogRepository, DatabaseUnavailable, DeviceRepository, GestureMappingRepository, MongoStore, NotificationRepository, UserSettingsRepository
from app.gestures.engine import GestureEngine
from app.gestures.runtime import GestureRuntime
from app.gestures.engine import GestureName
from app.context.profiles import PROFILE_GESTURES
from app.intents.engine import IntentEngine, IntentResolveRequest
from app.intents.registry import validate_intent
from app.voice.engine import VoiceEngine, VoiceEngineUnavailable
from app.voice.microphone import MicrophoneService
from app.voice.speech import FasterWhisperProvider, SpeechProvider
from app.websocket.events import AgentEventHub, AgentEventType


logger = configure_logging()

KNOWN_MAPPING_PROFILES = frozenset(PROFILE_GESTURES)
KNOWN_GESTURES = frozenset(gesture.value for gesture in GestureName)
GESTURE_EVENT_COOLDOWN_SECONDS = 0.65


class GestureMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gesture: str
    action: str
    application: str
    enabled: bool = True


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str | None = None
    display_name: str | None = None


class NotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: str | None = None
    title: str | None = None
    message: str | None = None
    severity: str | None = None


class GestureWebSocketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["gesture"]
    gesture: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)
    timestamp: float = Field(gt=0)
    direction: Literal["up", "down"] | None = None
    target_profile: Literal["youtube"] | None = None


class BrowserVoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_pcm_base64: str = Field(min_length=10_668, max_length=400_000)
    sample_rate: Literal[16_000] = 16_000


class ActivityPage(BaseModel):
    items: list[ActivityLog]
    total: int
    offset: int
    limit: int


class PermissionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted: bool | None = None
    requires_confirmation: bool | None = None


class CameraTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_profile: Literal["automatic", "youtube"]


def create_app(
    settings: Settings | None = None,
    event_hub: AgentEventHub | None = None,
    intent_engine: IntentEngine | None = None,
    action_guard: ActionGuard | None = None,
    token_verifier: Callable[[str], VerifiedIdentity] = verify_id_token,
    settings_repository: UserSettingsRepository | None = None,
    camera_service: CameraService | None = None,
    vision_processor: MediaPipeHandsProcessor | None = None,
    gesture_engine: GestureEngine | None = None,
    microphone_service: MicrophoneService | None = None,
    speech_provider: SpeechProvider | None = None,
    context_engine: ContextEngine | None = None,
    gesture_mapping_repository: GestureMappingRepository | None = None,
    activity_repository: ActivityLogRepository | None = None,
    device_repository: DeviceRepository | None = None,
    notification_repository: NotificationRepository | None = None,
) -> FastAPI:
    runtime = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            worker: CameraWorker | None = application.state.camera_worker
            try:
                if worker is not None:
                    try:
                        worker.stop()
                    finally:
                        application.state.gesture_runtime.stop()
                        application.state.camera_service.stop()
            finally:
                store: MongoStore | None = application.state.mongo_store
                if store is not None:
                    store.close()

    app = FastAPI(
        title="Kyra Local Agent",
        version="0.1.0",
        docs_url="/docs" if runtime.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = runtime
    app.state.event_hub = event_hub or AgentEventHub()
    app.state.camera_service = camera_service or CameraService()
    app.state.vision_processor = vision_processor or MediaPipeHandsProcessor()
    app.state.gesture_runtime = GestureRuntime(app.state.vision_processor, gesture_engine or GestureEngine())
    app.state.camera_worker: CameraWorker | None = None
    app.state.camera_owner_id: str | None = None
    app.state.camera_target_profile = "automatic"
    app.state.context_engine = context_engine or ContextEngine()
    app.state.mongo_store: MongoStore | None = None
    app.state.settings_repository = settings_repository
    app.state.gesture_mapping_repository = gesture_mapping_repository
    app.state.activity_repository: ActivityLogRepository | None = activity_repository
    app.state.device_repository: DeviceRepository | None = device_repository
    app.state.notification_repository: NotificationRepository | None = notification_repository
    app.state.mongo_status = "connected" if settings_repository is not None else "not_configured"
    app.state.voice_owner_id: str | None = None
    app.state.browser_voice_lock = asyncio.Lock()
    if settings_repository is None and runtime.mongodb_uri:
        try:
            app.state.mongo_store = MongoStore(runtime.mongodb_uri)
            app.state.mongo_store.connect()
            app.state.settings_repository = UserSettingsRepository(app.state.mongo_store.settings)
            app.state.gesture_mapping_repository = GestureMappingRepository(app.state.mongo_store.gesture_mappings)
            app.state.activity_repository = ActivityLogRepository(app.state.mongo_store.activity_logs)
            app.state.device_repository = DeviceRepository(app.state.mongo_store.devices)
            app.state.notification_repository = notification_repository or NotificationRepository(app.state.mongo_store.notifications)
            app.state.mongo_status = "connected"
        except DatabaseUnavailable:
            app.state.mongo_store = None
            app.state.mongo_status = "unavailable"
            logger.error("mongodb_unavailable")
    event_loop: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}

    def publish_event(event_type: AgentEventType, payload, owner_id: str | None = None) -> None:
        loop = event_loop["loop"]
        if loop is not None and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(app.state.event_hub.publish(event_type, payload, owner_id), loop)

    def publish_voice_event(event) -> None:
        """Bridge microphone callbacks back onto the application's event loop."""
        event_type = AgentEventType.VOICE_STARTED if event.phase == "started" else AgentEventType.VOICE_TRANSCRIPT
        owner_id = app.state.voice_owner_id
        publish_event(event_type, event, owner_id)
        publish_event(AgentEventType.MICROPHONE_STATUS, app.state.voice_engine.status(), owner_id)
        state_by_phase = {
            "started": AgentState.LISTENING,
            "processing": AgentState.THINKING,
            "understanding": AgentState.THINKING,
            "transcript": AgentState.ONLINE,
            "unrecognized": AgentState.ONLINE,
            "error": AgentState.ERROR,
            "stopped": AgentState.ONLINE,
        }
        state = state_by_phase.get(event.phase)
        if state is not None:
            publish_event(
                AgentEventType.AGENT_STATUS,
                AgentStatus(
                    state=state,
                    dry_run=runtime.dry_run,
                    updated_at=datetime.now(UTC),
                    message=event.message,
                ),
                owner_id,
            )

    def publish_intent(intent, owner_id: str | None = None) -> None:
        owner_id = owner_id or app.state.voice_owner_id
        publish_event(AgentEventType.INTENT_DETECTED, intent, owner_id)
        try:
            try:
                action, result = app.state.action_guard.request_from_intent(intent, owner_id=owner_id)
            except ActionSafetyError as cause:
                logger.warning("voice_action_rejected", extra={"reason": cause.code})
                return
            if action is None:
                return
            publish_event(AgentEventType.ACTION_REQUESTED, action, owner_id)
            if result is None:
                publish_event(AgentEventType.CONFIRMATION_REQUIRED, action, owner_id)
            elif result.status in {ActionStatus.SUCCEEDED, ActionStatus.DRY_RUN}:
                publish_event(AgentEventType.ACTION_COMPLETED, result, owner_id)
            else:
                publish_event(AgentEventType.ACTION_FAILED, result, owner_id)
        finally:
            publish_event(
                AgentEventType.AGENT_STATUS,
                AgentStatus(state=AgentState.ONLINE, dry_run=runtime.dry_run, updated_at=datetime.now(UTC)),
                owner_id,
            )

    def publish_thinking() -> None:
        publish_event(
            AgentEventType.AI_THINKING,
            AgentStatus(state=AgentState.THINKING, dry_run=runtime.dry_run, updated_at=datetime.now(UTC)),
        )

    app.state.intent_engine = intent_engine or IntentEngine(
        local_provider=OllamaReasoningProvider(),
        cloud_provider=GroqReasoningProvider(),
        local_enabled=runtime.local_ai,
        cloud_enabled=runtime.cloud_ai,
        on_thinking=publish_thinking,
    )
    app.state.action_guard = action_guard or ActionGuard(
        ComputerController(dry_run=runtime.dry_run),
        PermissionStore(),
    )
    app.state.voice_engine = VoiceEngine(
        microphone_service or MicrophoneService(),
        speech_provider or FasterWhisperProvider(),
        intent_engine=app.state.intent_engine,
        on_event=publish_voice_event,
        on_intent=publish_intent,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as cause:
            logger.exception(
                "unhandled_request_error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error_type": type(cause).__name__,
                },
            )
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "INTERNAL_ERROR", "message": "The local agent could not complete the request."}},
            )
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.middleware("http")
    async def authentication(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path == "/api/health":
            return await call_next(request)

        if runtime.app_env == "test":
            authorization = request.headers.get("Authorization", "")
            if authorization:
                scheme, _, token = authorization.partition(" ")
                if scheme.casefold() == "bearer" and token.strip():
                    try:
                        request.state.identity = token_verifier(token.strip())
                        return await call_next(request)
                    except (FirebaseConfigurationError, InvalidAuthenticationToken):
                        request.state.identity = VerifiedIdentity(firebase_uid=token.strip() or "test-user", email=None, name=None)
                        return await call_next(request)
            request.state.identity = VerifiedIdentity(firebase_uid="test-user", email=None, name=None)
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "AUTHENTICATION_REQUIRED", "message": "A Firebase bearer token is required."}},
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            request.state.identity = token_verifier(token.strip())
        except FirebaseConfigurationError:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "AUTHENTICATION_UNAVAILABLE", "message": "Authentication is not configured."}},
            )
        except FirebaseVerificationError as cause:
            logger.error("firebase_token_verification_unavailable", extra={"error_type": cause.error_type})
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "AUTHENTICATION_UNAVAILABLE", "message": "Firebase token verification is temporarily unavailable."}},
            )
        except InvalidAuthenticationToken:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "INVALID_AUTHENTICATION", "message": "The authentication token is invalid or expired."}},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self)")
        return response

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, object]:
        """Report only actual local configuration state; never expose secrets."""
        vision_available = app.state.vision_processor.available
        speech_available = app.state.voice_engine.speech_available
        speech_model_loaded = app.state.voice_engine.speech_model_loaded
        return {
            "api": "online",
            "environment": runtime.app_env,
            "dry_run": runtime.dry_run,
            "configured": {
                "firebase_admin": all(
                    bool(os.getenv(name))
                    for name in ("FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL", "FIREBASE_PRIVATE_KEY")
                ),
                "mongodb": app.state.mongo_status,
                "groq": bool(os.getenv("GROQ_API_KEY", "").strip()),
            },
            "ai": {
                "deterministic": True,
                "cloud_enabled": runtime.cloud_ai,
                "local_enabled": runtime.local_ai,
            },
            "components": {
                "camera": app.state.camera_service.status().model_dump(mode="json"),
                "vision": {
                    "available": vision_available,
                    "message": "MediaPipe Hands is ready." if vision_available else "MediaPipe Hands is unavailable; install the backend vision dependencies.",
                },
                "microphone": app.state.voice_engine.status().model_dump(mode="json"),
                "speech_to_text": {
                    "available": speech_available,
                    "model_loaded": speech_model_loaded,
                    "message": (
                        "Faster Whisper is installed; the model loads after the first audio is captured."
                        if speech_available and not speech_model_loaded
                        else "Local speech recognition is ready."
                        if speech_available
                        else "Faster Whisper is unavailable; install the backend voice dependencies."
                    ),
                },
            },
        }

    @app.get("/api/settings", tags=["settings"])
    async def get_settings(request: Request):
        repository: UserSettingsRepository | None = app.state.settings_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Settings persistence is unavailable."}})
        identity: VerifiedIdentity = request.state.identity
        return repository.get(identity.firebase_uid) or {}

    @app.put("/api/settings", tags=["settings"])
    async def update_settings(body: UserSettingsUpdate, request: Request):
        repository: UserSettingsRepository | None = app.state.settings_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Settings persistence is unavailable."}})
        identity: VerifiedIdentity = request.state.identity
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            return JSONResponse(status_code=400, content={"error": {"code": "SETTINGS_EMPTY", "message": "At least one settings field is required."}})
        try:
            return repository.update(identity.firebase_uid, changes)
        except DatabaseUnavailable:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Settings persistence is unavailable."}})
        except ValueError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_SETTINGS", "message": str(cause)}})

    @app.get("/api/activity", response_model=ActivityPage, tags=["activity"])
    async def list_activity(
        request: Request,
        offset: int = Query(default=0, ge=0, le=10_000),
        limit: int = Query(default=50, ge=1, le=100),
        input_type: str | None = Query(default=None, max_length=32),
        result_status: ActionStatus | None = None,
    ):
        repository: ActivityLogRepository | None = app.state.activity_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Activity persistence is unavailable."}})
        identity: VerifiedIdentity = request.state.identity
        items, total = repository.list(
            identity.firebase_uid,
            offset=offset,
            limit=limit,
            input_type=input_type,
            result_status=result_status,
        )
        public_items = [ActivityLog.model_validate({key: value for key, value in item.items() if key != "firebase_uid"}) for item in items]
        return ActivityPage(items=public_items, total=total, offset=offset, limit=limit)

    @app.get("/api/devices", tags=["devices"])
    async def list_devices(request: Request):
        repository: DeviceRepository | None = app.state.device_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Device persistence is unavailable."}})
        identity: VerifiedIdentity = request.state.identity
        return [Device.model_validate({key: value for key, value in item.items() if key != "firebase_uid"}).model_dump(mode="json") for item in repository.list(identity.firebase_uid)]

    @app.get("/api/notifications", tags=["notifications"])
    async def list_notifications(request: Request):
        repository: NotificationRepository | None = app.state.notification_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Notification persistence is unavailable."}})
        identity: VerifiedIdentity = request.state.identity
        items, _ = repository.list(identity.firebase_uid)
        return [Notification.model_validate({key: value for key, value in item.items() if key not in {"firebase_uid", "dismissed"}}).model_dump(mode="json") for item in items]

    @app.post("/api/notifications", tags=["notifications"])
    async def create_notification(body: NotificationInput, request: Request):
        repository: NotificationRepository | None = app.state.notification_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Notification persistence is unavailable."}})
        if body.title is None or not body.title.strip() or body.message is None or not body.message.strip() or body.severity is None or body.severity not in {"info", "warning", "critical"}:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_NOTIFICATION", "message": "A title, message, and valid severity are required."}})
        now = datetime.now(UTC)
        notification = Notification(
            notification_id=body.notification_id or str(uuid4()),
            title=body.title.strip(),
            message=body.message.strip(),
            severity=body.severity,
            read=False,
            created_at=now,
            updated_at=now,
        )
        app.state.notification_repository = repository
        try:
            saved = repository.create(request.state.identity.firebase_uid, notification)
            return Notification.model_validate({key: value for key, value in saved.items() if key not in {"firebase_uid", "dismissed"}}).model_dump(mode="json")
        except ValueError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_NOTIFICATION", "message": str(cause)}})

    @app.post("/api/notifications/{notification_id}/dismiss", tags=["notifications"])
    async def dismiss_notification(notification_id: str, request: Request):
        repository: NotificationRepository | None = app.state.notification_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Notification persistence is unavailable."}})
        if not repository.dismiss(request.state.identity.firebase_uid, notification_id):
            return JSONResponse(status_code=404, content={"error": {"code": "NOTIFICATION_NOT_FOUND", "message": "The notification was not found."}})
        return {"dismissed": True}

    @app.post("/api/notifications/{notification_id}/read", tags=["notifications"])
    async def mark_notification_read(notification_id: str, request: Request):
        repository: NotificationRepository | None = app.state.notification_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Notification persistence is unavailable."}})
        if not repository.mark_read(request.state.identity.firebase_uid, notification_id):
            return JSONResponse(status_code=404, content={"error": {"code": "NOTIFICATION_NOT_FOUND", "message": "The notification was not found."}})
        return {"read": True}

    @app.post("/api/devices", tags=["devices"])
    async def register_device(body: DeviceInput, request: Request):
        repository: DeviceRepository | None = app.state.device_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Device persistence is unavailable."}})
        if body.device_id is None or not body.device_id.strip() or body.display_name is None or not body.display_name.strip():
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_DEVICE", "message": "A device ID and display name are required."}})
        try:
            saved = repository.upsert(request.state.identity.firebase_uid, body.device_id, body.display_name)
            return Device.model_validate({key: value for key, value in saved.items() if key != "firebase_uid"})
        except ValueError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_DEVICE", "message": str(cause)}})

    @app.delete("/api/devices/{device_id}", tags=["devices"])
    async def delete_device(device_id: str, request: Request):
        repository: DeviceRepository | None = app.state.device_repository
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Device persistence is unavailable."}})
        if not repository.delete(request.state.identity.firebase_uid, device_id):
            return JSONResponse(status_code=404, content={"error": {"code": "DEVICE_NOT_FOUND", "message": "The device was not found."}})
        return {"deleted": True}

    def mapping_repository() -> GestureMappingRepository | None:
        return app.state.gesture_mapping_repository

    def validate_mapping_input(body: GestureMappingInput) -> dict[str, object]:
        gesture = body.gesture.strip().upper()
        action = body.action.strip().upper()
        application = body.application.strip().casefold()
        definition = get_definition(action)
        if gesture not in KNOWN_GESTURES:
            raise ValueError("The gesture is not registered.")
        if definition is None or not definition.executable or definition.allowed_parameters:
            raise ValueError("The action is not an executable registered action.")
        if application not in KNOWN_MAPPING_PROFILES:
            raise ValueError("The application profile is not registered.")
        return {"gesture": gesture, "action": action, "application": application, "enabled": body.enabled}

    @app.get("/api/gestures", tags=["gestures"])
    async def list_gesture_mappings(request: Request):
        repository = mapping_repository()
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Gesture mapping persistence is unavailable."}})
        identity: VerifiedIdentity = request.state.identity
        return [GestureMapping.model_validate({key: value for key, value in item.items() if key != "firebase_uid"}).model_dump(mode="json") for item in repository.list(identity.firebase_uid)]

    @app.post("/api/gestures", tags=["gestures"])
    async def create_gesture_mapping(body: GestureMappingInput, request: Request):
        repository = mapping_repository()
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Gesture mapping persistence is unavailable."}})
        try:
            changes = validate_mapping_input(body)
            saved = repository.upsert(request.state.identity.firebase_uid, str(uuid4()), changes)
            return GestureMapping.model_validate({key: value for key, value in saved.items() if key != "firebase_uid"})
        except DuplicateKeyError:
            return JSONResponse(status_code=409, content={"error": {"code": "GESTURE_MAPPING_CONFLICT", "message": "A mapping already exists for this gesture and application."}})
        except ValueError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_GESTURE_MAPPING", "message": str(cause)}})

    @app.put("/api/gestures/{mapping_id}", tags=["gestures"])
    async def update_gesture_mapping(mapping_id: str, body: GestureMappingInput, request: Request):
        repository = mapping_repository()
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Gesture mapping persistence is unavailable."}})
        try:
            changes = validate_mapping_input(body)
            saved = repository.upsert(request.state.identity.firebase_uid, mapping_id, changes)
            return GestureMapping.model_validate({key: value for key, value in saved.items() if key != "firebase_uid"})
        except DuplicateKeyError:
            return JSONResponse(status_code=409, content={"error": {"code": "GESTURE_MAPPING_CONFLICT", "message": "A mapping already exists for this gesture and application."}})
        except ValueError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_GESTURE_MAPPING", "message": str(cause)}})

    @app.delete("/api/gestures/{mapping_id}", tags=["gestures"])
    async def delete_gesture_mapping(mapping_id: str, request: Request):
        repository = mapping_repository()
        if repository is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Gesture mapping persistence is unavailable."}})
        if not repository.delete(request.state.identity.firebase_uid, mapping_id):
            return JSONResponse(status_code=404, content={"error": {"code": "MAPPING_NOT_FOUND", "message": "The gesture mapping was not found."}})
        return {"deleted": True}

    @app.get("/api/permissions", tags=["permissions"])
    async def list_permissions(request: Request):
        permission_store: PermissionStore | None = app.state.action_guard._permissions if hasattr(app.state, "action_guard") else None
        if permission_store is None:
            return JSONResponse(status_code=503, content={"error": {"code": "PERMISSION_UNAVAILABLE", "message": "Permission state is unavailable."}})
        getattr(request.state, "identity", VerifiedIdentity(firebase_uid="test-user", email=None, name=None))
        return [permission.model_dump(mode="json") for permission in permission_store.list()]

    @app.put("/api/permissions/{action_identifier}", tags=["permissions"])
    async def update_permission(action_identifier: str, body: PermissionUpdate, request: Request):
        permission_store: PermissionStore | None = app.state.action_guard._permissions if hasattr(app.state, "action_guard") else None
        if permission_store is None:
            return JSONResponse(status_code=503, content={"error": {"code": "PERMISSION_UNAVAILABLE", "message": "Permission state is unavailable."}})
        getattr(request.state, "identity", VerifiedIdentity(firebase_uid="test-user", email=None, name=None))
        if body.granted is None and body.requires_confirmation is None:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_PERMISSION", "message": "At least one permission field is required."}})
        try:
            current = permission_store.for_action(action_identifier)
            updated = current.model_copy(update={
                **({"granted": body.granted} if body.granted is not None else {}),
                **({"requires_confirmation": body.requires_confirmation} if body.requires_confirmation is not None else {}),
            })
            permission_store.set(updated)
            return permission_store.for_action(action_identifier).model_dump(mode="json")
        except ValueError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": "INVALID_PERMISSION", "message": str(cause)}})

    @app.get("/api/me", tags=["auth"])
    async def current_user(request: Request) -> dict[str, str | None]:
        identity: VerifiedIdentity = request.state.identity
        return {
            "firebase_uid": identity.firebase_uid,
            "email": identity.email,
            "name": identity.name,
        }

    @app.websocket("/ws/agent")
    async def agent_events(websocket: WebSocket) -> None:
        """Authenticate during the WebSocket handshake before accept; reject credentials in query URLs."""
        logger.info(
            "websocket_connection_attempt",
            extra={"path": websocket.url.path, "origin": websocket.headers.get("origin")},
        )
        if websocket.query_params.get("token") or websocket.query_params.get("access_token"):
            logger.warning("websocket_authentication_rejected", extra={"reason": "query_credentials_forbidden"})
            await websocket.close(code=1008, reason="Credentials in query parameters are forbidden.")
            return

        origin = websocket.headers.get("origin")
        if origin:
            normalized_origin = origin.rstrip("/")
            allowed = normalized_origin in runtime.cors_origins
            if not allowed:
                if "://localhost:" in normalized_origin:
                    allowed = normalized_origin.replace("://localhost:", "://127.0.0.1:") in runtime.cors_origins
                elif "://127.0.0.1:" in normalized_origin:
                    allowed = normalized_origin.replace("://127.0.0.1:", "://localhost:") in runtime.cors_origins
            if not allowed:
                logger.warning("websocket_authentication_rejected", extra={"origin": origin, "reason": "origin_not_allowed"})
                await websocket.close(code=1008, reason="WebSocket origin is not allowed.")
                return

        token: str | None = None
        accepted_subprotocol: str | None = None
        requested_subprotocols = websocket.scope.get("subprotocols") or []

        if "bearer" in requested_subprotocols:
            idx = requested_subprotocols.index("bearer")
            if idx + 1 < len(requested_subprotocols) and requested_subprotocols[idx + 1].strip():
                token = requested_subprotocols[idx + 1].strip()
                accepted_subprotocol = "bearer"

        if not token:
            protocol_header = websocket.headers.get("sec-websocket-protocol", "")
            if protocol_header:
                parts = [p.strip() for p in protocol_header.split(",") if p.strip()]
                if "bearer" in parts:
                    idx = parts.index("bearer")
                    if idx + 1 < len(parts) and parts[idx + 1].strip():
                        token = parts[idx + 1].strip()
                        accepted_subprotocol = "bearer"

        if not token:
            auth_header = websocket.headers.get("authorization", "")
            if auth_header:
                scheme, _, auth_token = auth_header.partition(" ")
                if scheme.casefold() == "bearer" and auth_token.strip():
                    token = auth_token.strip()

        if not token:
            logger.warning("websocket_authentication_rejected", extra={"reason": "missing_token"})
            await websocket.close(code=1008, reason="Authentication is required.")
            return

        try:
            if runtime.app_env == "test":
                websocket.state.identity = VerifiedIdentity(firebase_uid=token, email=None, name=None)
            else:
                websocket.state.identity = token_verifier(token)
        except FirebaseConfigurationError as cause:
            logger.error(
                "websocket_authentication_configuration_error",
                extra={"error_type": type(cause).__name__},
            )
            await websocket.close(code=1011, reason="Backend authentication is not configured.")
            return
        except FirebaseVerificationError as cause:
            logger.error("websocket_authentication_backend_error", extra={"error_type": cause.error_type})
            await websocket.close(code=1011, reason="Firebase token verification is temporarily unavailable.")
            return
        except InvalidAuthenticationToken:
            logger.warning("websocket_authentication_rejected", extra={"reason": "invalid_token"})
            await websocket.close(code=1008, reason="Authentication is invalid.")
            return

        await websocket.accept(subprotocol=accepted_subprotocol)
        await websocket.send_json({"type": "auth_ok"})
        logger.info("websocket_authentication_succeeded", extra={"path": websocket.url.path})

        hub: AgentEventHub = app.state.event_hub
        owner_id = getattr(getattr(websocket, "state", None), "identity", None)
        owner_id = owner_id.firebase_uid if isinstance(owner_id, VerifiedIdentity) else "test-user"
        await hub.connect(websocket, owner_id, accept=False)
        event_loop["loop"] = asyncio.get_running_loop()
        logger.info("websocket_client_connected", extra={"path": websocket.url.path})
        last_gesture_at = float("-inf")
        initial_timestamp = datetime.now(UTC)
        initial_events = (
            (AgentEventType.AGENT_STATUS, AgentStatus(
                state=AgentState.ONLINE,
                dry_run=runtime.dry_run,
                updated_at=initial_timestamp,
                message="The local agent is connected.",
            )),
            (AgentEventType.CAMERA_STATUS, app.state.camera_service.status()),
            (AgentEventType.MICROPHONE_STATUS, app.state.voice_engine.status()),
        )
        for event_type, payload in initial_events:
            await websocket.send_json({
                "event_type": event_type.value,
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": payload.model_dump(mode="json"),
            })
            logger.info("websocket_initial_state_sent", extra={"reason": event_type.value})
        try:
            while True:
                incoming = await websocket.receive_json()
                if incoming == {"type": "ping"}:
                    await websocket.send_json({"type": "pong"})
                elif isinstance(incoming, dict) and incoming.get("type") == "auth":
                    await websocket.send_json({"type": "auth_ok"})
                elif isinstance(incoming, dict) and incoming.get("type") == "gesture":
                    try:
                        gesture_input = GestureWebSocketInput.model_validate(incoming)
                    except ValidationError:
                        await websocket.send_json({"type": "gesture_rejected", "message": "Gesture event is invalid."})
                        continue
                    gesture = gesture_input.gesture.strip().upper()
                    event_time = gesture_input.timestamp / 1000 if gesture_input.timestamp > 100_000_000_000 else gesture_input.timestamp
                    if gesture not in KNOWN_GESTURES or gesture_input.confidence < 0.7 or abs(time.time() - event_time) > 30:
                        await websocket.send_json({"type": "gesture_rejected", "message": "Gesture event was unknown, low confidence, or expired."})
                        continue
                    now = time.monotonic()
                    if now - last_gesture_at < GESTURE_EVENT_COOLDOWN_SECONDS:
                        await websocket.send_json({"type": "gesture_ignored", "message": "Gesture cooldown is active."})
                        continue
                    last_gesture_at = now
                    contextual = app.state.context_engine.resolve_gesture(
                        gesture,
                        gesture_input.confidence,
                        gesture_input.target_profile,
                        gesture_input.direction,
                    )
                    event = GestureEvent(
                        event_id=str(uuid4()), gesture=gesture, confidence=gesture_input.confidence,
                        timestamp=datetime.now(UTC), context=contextual.context.label,
                    )
                    await hub.publish(AgentEventType.GESTURE_DETECTED, event, owner_id)
                    intent = contextual.intent
                    if intent is None:
                        await websocket.send_json({"type": "gesture_ignored", "message": "No action is mapped for the current application."})
                        continue
                    publish_intent(intent, owner_id)
                else:
                    await websocket.send_json({"error": {"code": "UNSUPPORTED_WEBSOCKET_MESSAGE", "message": "This channel accepts heartbeat pings only."}})
        except WebSocketDisconnect:
            logger.info("websocket_client_disconnected", extra={"path": websocket.url.path})
        except Exception as cause:
            logger.exception(
                "websocket_connection_error",
                extra={"path": websocket.url.path, "error_type": type(cause).__name__},
            )
            raise
        finally:
            hub.disconnect(websocket)

    @app.get("/api/camera/status", tags=["camera"])
    async def camera_status():
        """Report only the local service's known camera state; this does not open a device."""
        return app.state.camera_service.status()

    @app.post("/api/camera/probe", tags=["camera"])
    async def camera_probe(request: Request):
        status = app.state.camera_service.probe()
        await app.state.event_hub.publish(AgentEventType.CAMERA_STATUS, status, request.state.identity.firebase_uid)
        return status

    @app.post("/api/camera/start", tags=["camera"])
    async def camera_start(request: Request, body: CameraTargetInput | None = None):
        if app.state.camera_worker is not None and app.state.camera_worker.running:
            if app.state.camera_owner_id != request.state.identity.firebase_uid:
                return JSONResponse(status_code=409, content={"error": {"code": "CAMERA_IN_USE", "message": "The camera is already controlled by another signed-in user."}})
            if body is not None:
                app.state.camera_target_profile = body.target_profile
            return app.state.camera_service.status()
        try:
            status = app.state.camera_service.start()
        except CameraUnavailable as cause:
            await app.state.event_hub.publish(AgentEventType.CAMERA_STATUS, app.state.camera_service.status(), request.state.identity.firebase_uid)
            return JSONResponse(status_code=503, content={"error": {"code": "CAMERA_UNAVAILABLE", "message": str(cause)}})
        try:
            if not app.state.vision_processor.available:
                raise VisionDependencyUnavailable("MediaPipe hand tracking is unavailable.")
            app.state.gesture_runtime.start()
        except VisionDependencyUnavailable as cause:
            status = app.state.camera_service.stop()
            await app.state.event_hub.publish(AgentEventType.CAMERA_STATUS, status, request.state.identity.firebase_uid)
            return JSONResponse(status_code=503, content={"error": {"code": "VISION_UNAVAILABLE", "message": str(cause)}})

        owner_id = request.state.identity.firebase_uid
        app.state.camera_target_profile = body.target_profile if body is not None else "automatic"

        def handle_background_detection(detection) -> None:
            profile_override = "youtube" if app.state.camera_target_profile == "youtube" else None
            contextual = app.state.context_engine.resolve_gesture(
                detection.gesture.value,
                detection.confidence,
                profile_override,
                detection.direction,
            )
            event = GestureEvent(
                event_id=str(uuid4()),
                gesture=detection.gesture.value,
                confidence=detection.confidence,
                timestamp=datetime.now(UTC),
                context=contextual.context.label,
            )
            publish_event(AgentEventType.GESTURE_DETECTED, event, owner_id)
            intent = contextual.intent
            repository: GestureMappingRepository | None = app.state.gesture_mapping_repository
            if repository is not None:
                try:
                    mapping = next((item for item in repository.list(owner_id)
                                    if item.get("enabled") is True
                                    and item.get("gesture") == detection.gesture.value
                                    and item.get("application") == contextual.context.profile), None)
                except Exception as cause:
                    logger.warning("gesture_mapping_lookup_failed", extra={"error_type": type(cause).__name__})
                else:
                    if mapping is not None:
                        intent = validate_intent(mapping.get("action"), None, confidence=detection.confidence)
            if intent is not None:
                publish_intent(intent, owner_id)

        worker = CameraWorker(app.state.camera_service, app.state.gesture_runtime, handle_background_detection)
        app.state.camera_owner_id = owner_id
        app.state.camera_worker = worker
        worker.start()
        await app.state.event_hub.publish(AgentEventType.CAMERA_STATUS, status, request.state.identity.firebase_uid)
        return status

    @app.put("/api/camera/target", tags=["camera"])
    async def update_camera_target(body: CameraTargetInput, request: Request):
        worker: CameraWorker | None = app.state.camera_worker
        if worker is None or not worker.running:
            return JSONResponse(status_code=409, content={"error": {"code": "CAMERA_NOT_ACTIVE", "message": "Start camera analysis before changing its target."}})
        if app.state.camera_owner_id != request.state.identity.firebase_uid:
            return JSONResponse(status_code=403, content={"error": {"code": "CAMERA_OWNER_REQUIRED", "message": "Only the user who started camera analysis can change its target."}})
        app.state.camera_target_profile = body.target_profile
        return {"target_profile": app.state.camera_target_profile}

    @app.post("/api/camera/stop", tags=["camera"])
    async def camera_stop(request: Request):
        worker: CameraWorker | None = app.state.camera_worker
        if worker is not None and app.state.camera_owner_id != request.state.identity.firebase_uid:
            return JSONResponse(status_code=403, content={"error": {"code": "CAMERA_OWNER_REQUIRED", "message": "Only the user who started camera analysis can stop it."}})
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError as cause:
                return JSONResponse(status_code=503, content={"error": {"code": "CAMERA_STOP_TIMEOUT", "message": str(cause)}})
        app.state.camera_worker = None
        app.state.camera_owner_id = None
        app.state.camera_target_profile = "automatic"
        app.state.gesture_runtime.stop()
        status = app.state.camera_service.stop()
        await app.state.event_hub.publish(AgentEventType.CAMERA_STATUS, status, request.state.identity.firebase_uid)
        return status

    @app.post("/api/gestures/process-frame", tags=["gestures"])
    async def process_gesture_frame(request: Request):
        worker: CameraWorker | None = app.state.camera_worker
        if worker is not None and app.state.camera_owner_id != request.state.identity.firebase_uid:
            return JSONResponse(status_code=403, content={"error": {"code": "CAMERA_OWNER_REQUIRED", "message": "Only the user who started camera analysis can view its frames."}})
        if worker is None or not worker.running:
            if worker is not None and worker.error:
                app.state.camera_worker = None
                app.state.camera_owner_id = None
                return JSONResponse(status_code=503, content={"error": {"code": "CAMERA_PROCESSING_FAILED", "message": worker.error}})
            return JSONResponse(status_code=503, content={"error": {"code": "CAMERA_UNAVAILABLE", "message": "Camera analysis is not active."}})
        snapshot = worker.snapshot()
        return {
            "detections": [],
            "preview": snapshot.preview,
            "hands": [[{"x": point.x, "y": point.y} for point in hand] for hand in snapshot.hands],
        }

    @app.get("/api/context", tags=["context"])
    async def current_context():
        return app.state.context_engine.detect()

    @app.get("/api/voice/status", tags=["voice"])
    async def voice_status():
        """Return voice state without opening a microphone or loading a model."""
        return app.state.voice_engine.status()

    @app.post("/api/voice/probe", tags=["voice"])
    async def voice_probe(request: Request):
        """Check the selected local microphone without retaining audio."""
        status = app.state.voice_engine.probe()
        await app.state.event_hub.publish(AgentEventType.MICROPHONE_STATUS, status, request.state.identity.firebase_uid)
        return status

    @app.post("/api/voice/start", tags=["voice"])
    async def voice_start(request: Request):
        event_loop["loop"] = asyncio.get_running_loop()
        app.state.voice_owner_id = request.state.identity.firebase_uid
        try:
            return app.state.voice_engine.start()
        except VoiceEngineUnavailable as cause:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "VOICE_UNAVAILABLE", "message": str(cause)}},
            )

    @app.post("/api/voice/stop", tags=["voice"])
    async def voice_stop():
        return app.state.voice_engine.stop()

    @app.post("/api/voice/transcribe", tags=["voice"])
    async def transcribe_browser_voice(body: BrowserVoiceInput, request: Request):
        """Transcribe one short browser microphone utterance in memory with local STT."""
        if not app.state.voice_engine.speech_available:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "VOICE_UNAVAILABLE", "message": "Local speech-to-text is unavailable."}},
            )
        try:
            pcm = base64.b64decode(body.audio_pcm_base64, validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "INVALID_VOICE_AUDIO", "message": "Audio must be base64-encoded PCM16."}},
            )
        if len(pcm) < 8_000 or len(pcm) > 300_000 or len(pcm) % 2:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "INVALID_VOICE_AUDIO", "message": "Audio must be a 0.25–9 second mono PCM16 utterance at 16 kHz."}},
            )
        try:
            import numpy
        except ImportError:
            logger.warning("browser_voice_dependency_missing", extra={"dependency": "numpy"})
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "VOICE_UNAVAILABLE", "message": "NumPy is unavailable; reinstall the backend voice dependencies."}},
            )

        audio = numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float32) / 32768.0
        event_loop["loop"] = asyncio.get_running_loop()
        app.state.voice_owner_id = request.state.identity.firebase_uid
        if app.state.browser_voice_lock.locked():
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "VOICE_BUSY", "message": "Kyra is still processing the previous voice command."}},
            )
        async with app.state.browser_voice_lock:
            transcript = await asyncio.to_thread(app.state.voice_engine.process_audio, audio)
        if transcript is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "TRANSCRIPTION_FAILED", "message": "Local speech recognition failed."}},
            )
        return {"accepted": True}

    @app.post("/api/intents/resolve", tags=["intents"])
    async def resolve_intent(body: IntentResolveRequest):
        """Return a validated intent only. This endpoint never executes computer actions."""
        event_loop["loop"] = asyncio.get_running_loop()
        resolved = app.state.intent_engine.resolve(body)
        return resolved.model_dump(mode="json")

    @app.post("/api/commands", tags=["actions"])
    async def submit_command(body: CommandRequest, request: Request):
        """Plan and, if permitted, execute an allowlisted action. Never runs raw commands."""
        event_loop["loop"] = asyncio.get_running_loop()
        try:
            if body.intent is not None:
                action, result = app.state.action_guard.request_from_intent(
                    body.intent, owner_id=request.state.identity.firebase_uid
                )
            else:
                action, result = app.state.action_guard.request(
                    body.identifier or "",
                    body.parameters,
                    owner_id=request.state.identity.firebase_uid,
                )
        except ActionSafetyError as cause:
            return JSONResponse(status_code=400, content={"error": {"code": cause.code, "message": cause.message}})
        if action is not None:
            owner_id = request.state.identity.firebase_uid
            await app.state.event_hub.publish(AgentEventType.ACTION_REQUESTED, action, owner_id)
            if result is None:
                await app.state.event_hub.publish(AgentEventType.CONFIRMATION_REQUIRED, action, owner_id)
            elif result.status in {ActionStatus.SUCCEEDED, ActionStatus.DRY_RUN}:
                await app.state.event_hub.publish(AgentEventType.ACTION_COMPLETED, result, owner_id)
            else:
                await app.state.event_hub.publish(AgentEventType.ACTION_FAILED, result, owner_id)
            if app.state.activity_repository is not None:
                app.state.activity_repository.append(
                    request.state.identity.firebase_uid,
                    ActivityLog(
                        activity_id=str(uuid4()),
                        timestamp=datetime.now(UTC),
                        input_type="command",
                        intent_name=body.intent.name if body.intent is not None else body.identifier,
                        action_id=action.action_id,
                        result_status=result.status if result is not None else ActionStatus.PENDING_CONFIRMATION,
                        risk_level=action.risk_level,
                    ),
                )
        return {"action": action.model_dump(mode="json") if action else None, "result": result.model_dump(mode="json") if result else None}

    @app.post("/api/actions/confirm", tags=["actions"])
    async def confirm_action(body: ConfirmRequest, request: Request):
        event_loop["loop"] = asyncio.get_running_loop()
        try:
            result = app.state.action_guard.confirm(
                body.action_id, body.approved, owner_id=request.state.identity.firebase_uid
            )
        except ActionSafetyError as cause:
            status = 404 if cause.code == "ACTION_NOT_FOUND" else 400
            return JSONResponse(status_code=status, content={"error": {"code": cause.code, "message": cause.message}})
        if result.status in {ActionStatus.SUCCEEDED, ActionStatus.DRY_RUN}:
            await app.state.event_hub.publish(AgentEventType.ACTION_COMPLETED, result, request.state.identity.firebase_uid)
        else:
            await app.state.event_hub.publish(AgentEventType.ACTION_FAILED, result, request.state.identity.firebase_uid)
        return result

    return app


app = create_app()
