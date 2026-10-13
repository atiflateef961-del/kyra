import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.contracts.models import AgentState, AgentStatus
from app.core.config import Settings
from app.auth.firebase import VerifiedIdentity
from app.actions.safety import ActionGuard
from app.computer.controller import ComputerController, NativeWindowsExecutor
from app.context.detect import ForegroundWindow
from app.context.engine import ContextEngine
from app.main import create_app
from app.websocket.events import AgentEventHub, AgentEventType


class RecordingSocket:
    """Explicit test-only socket used to verify event delivery without a network."""

    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


def test_event_hub_validates_and_broadcasts_server_events() -> None:
    hub = AgentEventHub()
    socket = RecordingSocket()

    asyncio.run(hub.connect(socket))  # type: ignore[arg-type]
    asyncio.run(
        hub.publish(
            AgentEventType.AGENT_STATUS,
            AgentStatus(state=AgentState.ONLINE, dry_run=True, updated_at=datetime.now(UTC)),
        )
    )

    assert socket.accepted is True
    assert socket.messages[0]["event_type"] == "agent_status"
    assert socket.messages[0]["payload"]["dry_run"] is True  # type: ignore[index]


def test_event_hub_isolates_owner_scoped_events() -> None:
    hub = AgentEventHub()
    user_a = RecordingSocket()
    user_b = RecordingSocket()

    asyncio.run(hub.connect(user_a, "user-a"))  # type: ignore[arg-type]
    asyncio.run(hub.connect(user_b, "user-b"))  # type: ignore[arg-type]
    asyncio.run(
        hub.publish(
            AgentEventType.AGENT_STATUS,
            AgentStatus(state=AgentState.ONLINE, dry_run=True, updated_at=datetime.now(UTC)),
            "user-a",
        )
    )

    assert len(user_a.messages) == 1
    assert user_b.messages == []


def test_websocket_connects_reconnects_and_answers_heartbeat() -> None:
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
    )
    client = TestClient(app)

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as first_connection:
        assert first_connection.receive_json() == {"type": "auth_ok"}
        initial_state = [first_connection.receive_json() for _ in range(3)]
        assert [event["event_type"] for event in initial_state] == [
            "agent_status",
            "camera_status",
            "microphone_status",
        ]
        assert initial_state[0]["payload"]["state"] == "online"
        assert initial_state[0]["payload"]["dry_run"] is True
        assert initial_state[1]["payload"]["available"] is None
        assert initial_state[1]["payload"]["active"] is False
        assert initial_state[2]["payload"]["available"] is None
        assert initial_state[2]["payload"]["active"] is False
        first_connection.send_json({"type": "ping"})
        assert first_connection.receive_json() == {"type": "pong"}
    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as second_connection:
        assert second_connection.receive_json() == {"type": "auth_ok"}
        assert [second_connection.receive_json()["event_type"] for _ in range(3)] == [
            "agent_status",
            "camera_status",
            "microphone_status",
        ]
        second_connection.send_json({"type": "ping"})
        assert second_connection.receive_json() == {"type": "pong"}


def test_websocket_refuses_client_commands() -> None:
    app = create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True))
    client = TestClient(app)

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        connection.send_json({"type": "execute", "command": "shutdown"})
        assert connection.receive_json()["error"]["code"] == "UNSUPPORTED_WEBSOCKET_MESSAGE"


@pytest.mark.parametrize(
    ("gesture", "expected_action", "direction"),
    (
        ("THUMBS_UP", "VOLUME_UP", None),
        ("THUMBS_DOWN", "VOLUME_DOWN", None),
        ("SWIPE_LEFT", "NEXT_YOUTUBE_VIDEO", None),
        ("SWIPE_RIGHT", "PREVIOUS_YOUTUBE_VIDEO", None),
        ("SCROLL", "SCROLL_UP", "up"),
        ("SCROLL", "SCROLL_DOWN", "down"),
    ),
)
def test_authenticated_websocket_gesture_reaches_action_guard(gesture: str, expected_action: str, direction: str | None) -> None:
    class YouTubeReader:
        def read(self):
            return ForegroundWindow("chrome.exe", "YouTube video")

    class RecordingGuard(ActionGuard):
        def __init__(self):
            super().__init__(ComputerController(dry_run=True))
            self.intents = []

        def request_from_intent(self, intent, *, owner_id=None):
            self.intents.append(intent.name)
            return super().request_from_intent(intent, owner_id=owner_id)

    guard = RecordingGuard()
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
        context_engine=ContextEngine(YouTubeReader()),  # type: ignore[arg-type]
        action_guard=guard,
    )
    client = TestClient(app)

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        message = {"type": "gesture", "gesture": gesture, "confidence": 0.94, "timestamp": __import__("time").time() * 1000}
        if direction:
            message["direction"] = direction
        connection.send_json(message)
        received = [connection.receive_json() for _ in range(4)]

    assert guard.intents == [expected_action]
    assert [event["event_type"] for event in received] == ["gesture_detected", "intent_detected", "action_requested", "action_completed"]
    assert received[-1]["payload"]["status"] == "dry_run"  # type: ignore[index]


def test_websocket_gesture_events_are_debounced_per_connection() -> None:
    class YouTubeReader:
        def read(self):
            return ForegroundWindow("chrome.exe", "YouTube video")

    class RecordingGuard(ActionGuard):
        def __init__(self):
            super().__init__(ComputerController(dry_run=True))
            self.intents = []

        def request_from_intent(self, intent, *, owner_id=None):
            self.intents.append(intent.name)
            return super().request_from_intent(intent, owner_id=owner_id)

    guard = RecordingGuard()
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
        context_engine=ContextEngine(YouTubeReader()),  # type: ignore[arg-type]
        action_guard=guard,
    )
    client = TestClient(app)
    message = {"type": "gesture", "gesture": "SWIPE_LEFT", "confidence": 0.94, "timestamp": __import__("time").time() * 1000}

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        connection.send_json(message)
        for _ in range(4):
            connection.receive_json()
        message["timestamp"] = __import__("time").time() * 1000
        connection.send_json(message)
        duplicate = None
        for _ in range(8):
            response = connection.receive_json()
            if response.get("type") == "gesture_ignored":
                duplicate = response
                break

    assert duplicate == {"type": "gesture_ignored", "message": "Gesture cooldown is active."}
    assert guard.intents == ["NEXT_YOUTUBE_VIDEO"]


def test_websocket_rejects_low_confidence_gesture_without_action() -> None:
    app = create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True))
    client = TestClient(app)

    with client.websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        connection.send_json({"type": "gesture", "gesture": "SWIPE_RIGHT", "confidence": 0.2, "timestamp": __import__("time").time() * 1000})
        assert connection.receive_json()["type"] == "gesture_rejected"


def test_explicit_youtube_target_routes_swipe_while_kyra_is_foreground() -> None:
    class KyraReader:
        def read(self):
            return ForegroundWindow("chrome.exe", "KYRA")

    class RecordingGuard(ActionGuard):
        def __init__(self):
            super().__init__(ComputerController(dry_run=True))
            self.intents = []

        def request_from_intent(self, intent, *, owner_id=None):
            self.intents.append(intent.name)
            return super().request_from_intent(intent, owner_id=owner_id)

    guard = RecordingGuard()
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
        context_engine=ContextEngine(KyraReader()),  # type: ignore[arg-type]
        action_guard=guard,
    )

    with TestClient(app).websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        connection.send_json({
            "type": "gesture",
            "gesture": "SWIPE_LEFT",
            "confidence": 0.94,
            "timestamp": __import__("time").time() * 1000,
            "target_profile": "youtube",
        })
        received = [connection.receive_json() for _ in range(4)]

    assert guard.intents == ["NEXT_YOUTUBE_VIDEO"]
    assert received[0]["payload"]["context"] == "YouTube (selected target)"  # type: ignore[index]


def test_authenticated_youtube_swipe_dispatches_native_media_key_without_dry_run() -> None:
    class KyraReader:
        def read(self):
            return ForegroundWindow("chrome.exe", "KYRA")

    class RecordingUser32:
        def __init__(self) -> None:
            self.key_events: list[tuple[int, int, int, int]] = []

        def SendInput(self, count, inputs, input_size) -> int:
            for index in range(count):
                event = inputs[index]
                if event.type == NativeWindowsExecutor._INPUT_KEYBOARD:
                    self.key_events.append((event.keyboard.virtual_key, 0, event.keyboard.flags, 0))
            return count

    user32 = RecordingUser32()
    # Exercise NativeWindowsExecutor's real input construction while recording
    # SendInput calls so this integration test does not alter the desktop.
    executor = NativeWindowsExecutor.__new__(NativeWindowsExecutor)
    executor._user32 = user32  # type: ignore[attr-defined]
    controller = ComputerController(dry_run=False, executor=executor)
    guard = ActionGuard(controller)
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=False),
        token_verifier=lambda token: VerifiedIdentity(firebase_uid=token, email=None, name=None),
        context_engine=ContextEngine(KyraReader()),  # type: ignore[arg-type]
        action_guard=guard,
    )

    with TestClient(app).websocket_connect("/ws/agent", subprotocols=["bearer", "test-user"]) as connection:
        assert connection.receive_json() == {"type": "auth_ok"}
        for _ in range(3):
            connection.receive_json()
        connection.send_json({
            "type": "gesture",
            "gesture": "SWIPE_LEFT",
            "confidence": 0.94,
            "timestamp": __import__("time").time() * 1000,
            "target_profile": "youtube",
        })
        received = [connection.receive_json() for _ in range(4)]

    assert user32.key_events == [
        (0xB0, 0, 0, 0),
        (0xB0, 0, NativeWindowsExecutor._KEY_UP, 0),
    ]
    assert received[1]["payload"]["name"] == "NEXT_YOUTUBE_VIDEO"  # type: ignore[index]
    assert received[-1]["event_type"] == "action_completed"
    assert received[-1]["payload"]["status"] == "succeeded"  # type: ignore[index]
