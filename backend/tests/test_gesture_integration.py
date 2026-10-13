from types import SimpleNamespace
from threading import Event

from fastapi.testclient import TestClient

from app.camera.service import CameraService
from app.actions.safety import ActionGuard
from app.computer.controller import ComputerController
from app.context.detect import ForegroundWindow
from app.context.engine import ContextEngine
from app.core.config import Settings
from app.gestures.engine import GestureEngine, Landmark
from app.main import create_app
from tests.test_gestures import make_hand


class FakeCapture:
    def isOpened(self) -> bool:
        return True

    def read(self):
        return True, "local-frame"

    def release(self) -> None:
        pass


class FakeVision:
    available = True

    def __init__(self, hand) -> None:
        self._hand = hand
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def process_bgr_frame(self, frame):
        assert frame == "local-frame"
        landmarks = [SimpleNamespace(x=point.x, y=point.y) for point in self._hand.points]
        return SimpleNamespace(multi_hand_landmarks=[SimpleNamespace(landmark=landmarks)])


class FakeForegroundReader:
    def read(self) -> ForegroundWindow:
        return ForegroundWindow("chrome.exe", "YouTube - test video")


class RecordingActionGuard(ActionGuard):
    def __init__(self, controller: ComputerController | None = None) -> None:
        super().__init__(controller or ComputerController(dry_run=True))
        self.requested: list[str] = []
        self.requested_event = Event()

    def request_from_intent(self, intent, *, owner_id=None):
        self.requested.append(intent.name)
        result = super().request_from_intent(intent, owner_id=owner_id)
        self.requested_event.set()
        return result


class SequencedVision(FakeVision):
    def __init__(self, hands) -> None:
        self._hands = hands
        self._index = 0
        self.started = False
        self.stopped = False

    def process_bgr_frame(self, frame):
        assert frame == "local-frame"
        hand = self._hands[min(self._index, len(self._hands) - 1)]
        self._index += 1
        landmarks = [SimpleNamespace(x=point.x, y=point.y) for point in hand.points]
        return SimpleNamespace(multi_hand_landmarks=[SimpleNamespace(landmark=landmarks)])


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls = []

    def press_virtual_key(self, key_code: int) -> None:
        self.calls.append(("key", key_code))

    def control_media(self, action: str) -> None:
        self.calls.append(("media", action))

    def press_key_combo(self, key_codes: tuple[int, ...]) -> None:
        self.calls.append(("combo", key_codes))

    def scroll(self, delta: int) -> None:
        self.calls.append(("scroll", delta))

    def adjust_volume(self, delta: float) -> tuple[float, float]:
        self.calls.append(("volume", delta))
        return 0.5, 0.5 + delta

    def launch(self, executable: str) -> None:
        self.calls.append(("launch", executable))


def _settings() -> Settings:
    return Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True)


def test_background_camera_worker_processes_gesture_without_frame_polling() -> None:
    vision = FakeVision(make_hand(index_y=0.25, thumb_y=0.25, middle=True, ring=True, pinky=True))
    guard = RecordingActionGuard()
    app = create_app(
        _settings(),
        camera_service=CameraService(capture_factory=lambda _: FakeCapture()),
        vision_processor=vision,  # type: ignore[arg-type]
        gesture_engine=GestureEngine(cooldown_seconds=0),
        context_engine=ContextEngine(FakeForegroundReader()),
        action_guard=guard,
    )
    client = TestClient(app)

    assert client.post("/api/camera/start").status_code == 200
    assert guard.requested_event.wait(1)
    response = client.post("/api/gestures/process-frame")

    assert response.status_code == 200
    assert response.json()["hands"]
    assert vision.started is True
    assert guard.requested == ["PAUSE"]
    assert client.post("/api/camera/stop").json()["active"] is False


def test_youtube_left_swipe_flows_from_camera_frame_to_next_media_key() -> None:
    vision = SequencedVision((make_hand(wrist_x=0.5), make_hand(wrist_x=0.8)))
    executor = RecordingExecutor()
    guard = RecordingActionGuard(ComputerController(dry_run=False, executor=executor))
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=False),
        camera_service=CameraService(capture_factory=lambda _: FakeCapture()),
        vision_processor=vision,  # type: ignore[arg-type]
        gesture_engine=GestureEngine(cooldown_seconds=0),
        context_engine=ContextEngine(FakeForegroundReader()),
        action_guard=guard,
    )
    client = TestClient(app)

    assert client.post("/api/camera/start").status_code == 200
    assert guard.requested_event.wait(1)
    assert executor.calls == [("combo", (0xB0,))]
    assert client.post("/api/camera/stop").json()["active"] is False


def test_thumb_up_from_camera_requests_windows_volume_increase() -> None:
    vision = FakeVision(make_hand(thumb_y=0.25))
    executor = RecordingExecutor()
    guard = RecordingActionGuard(ComputerController(dry_run=False, executor=executor))
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=False),
        camera_service=CameraService(capture_factory=lambda _: FakeCapture()),
        vision_processor=vision,  # type: ignore[arg-type]
        gesture_engine=GestureEngine(cooldown_seconds=0),
        context_engine=ContextEngine(FakeForegroundReader()),
        action_guard=guard,
    )
    client = TestClient(app)

    assert client.post("/api/camera/start").status_code == 200
    assert guard.requested_event.wait(1)

    assert guard.requested == ["VOLUME_UP"]
    assert executor.calls == [("volume", 0.05)]
    assert client.post("/api/camera/stop").json()["active"] is False


def test_closed_fist_from_camera_requests_media_play() -> None:
    points = list(make_hand().points)
    points[4] = Landmark(0.51, 0.51)
    vision = FakeVision(type(make_hand())(tuple(points)))
    executor = RecordingExecutor()
    guard = RecordingActionGuard(ComputerController(dry_run=False, executor=executor))
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=False),
        camera_service=CameraService(capture_factory=lambda _: FakeCapture()),
        vision_processor=vision,  # type: ignore[arg-type]
        gesture_engine=GestureEngine(cooldown_seconds=0),
        context_engine=ContextEngine(FakeForegroundReader()),
        action_guard=guard,
    )
    client = TestClient(app)

    assert client.post("/api/camera/start").status_code == 200
    assert guard.requested_event.wait(1)

    assert guard.requested == ["PLAY"]
    assert executor.calls == [("media", "play")]
    assert client.post("/api/camera/stop").json()["active"] is False


def test_owner_gesture_mapping_overrides_context_action() -> None:
    class MappingRepository:
        def list(self, owner_id):
            return [{
                "gesture": "OPEN_PALM",
                "action": "VOLUME_DOWN",
                "application": "youtube",
                "enabled": True,
            }]

    vision = FakeVision(make_hand(index_y=0.25, thumb_y=0.25, middle=True, ring=True, pinky=True))
    guard = RecordingActionGuard()
    app = create_app(
        _settings(),
        camera_service=CameraService(capture_factory=lambda _: FakeCapture()),
        vision_processor=vision,  # type: ignore[arg-type]
        gesture_engine=GestureEngine(cooldown_seconds=0),
        context_engine=ContextEngine(FakeForegroundReader()),
        gesture_mapping_repository=MappingRepository(),  # type: ignore[arg-type]
        action_guard=guard,
    )
    client = TestClient(app)

    assert client.post("/api/camera/start").status_code == 200
    assert guard.requested_event.wait(1)

    assert guard.requested == ["VOLUME_DOWN"]
    assert client.post("/api/camera/stop").json()["active"] is False


def test_gesture_frame_requires_active_camera() -> None:
    app = create_app(_settings(), vision_processor=FakeVision(make_hand()))  # type: ignore[arg-type]

    response = TestClient(app).post("/api/gestures/process-frame")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CAMERA_UNAVAILABLE"
