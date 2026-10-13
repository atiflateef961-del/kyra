import pytest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.camera.service import CameraService, CameraUnavailable
from app.camera.vision import MediaPipeHandsProcessor, VisionDependencyUnavailable
from app.core.config import Settings
from app.main import create_app


class FakeCapture:
    def __init__(self, opened: bool = True, *, frame_ok: bool = True, frame: object = "test-frame") -> None:
        self.opened = opened
        self.frame_ok = frame_ok
        self.frame = frame
        self.released = False
        self.read_count = 0

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        self.read_count += 1
        return self.frame_ok, self.frame

    def release(self) -> None:
        self.released = True


class FailingVision:
    available = True

    def start(self) -> None:
        raise VisionDependencyUnavailable("MediaPipe test dependency is unavailable.")

    def stop(self) -> None:
        pass


class EmptyVision:
    available = True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def process_bgr_frame(self, frame):
        from types import SimpleNamespace

        return SimpleNamespace(multi_hand_landmarks=[])


def test_camera_is_not_opened_at_construction_and_reports_unknown_availability() -> None:
    service = CameraService(opencv_module=None)

    status = service.status()

    assert status.active is False
    assert status.available is None


def test_camera_lifecycle_uses_explicit_test_capture() -> None:
    capture = FakeCapture()
    service = CameraService(capture_factory=lambda _: capture)

    assert service.start().active is True
    assert service.read_frame() == "test-frame"
    assert service.stop().active is False
    assert capture.released is True
    assert capture.read_count == 1  # the validated startup frame is reused by the worker


def test_camera_probe_requires_a_frame_and_releases_capture() -> None:
    capture = FakeCapture(frame_ok=False, frame=None)
    service = CameraService(capture_factory=lambda _: capture)

    status = service.probe()

    assert status.available is False
    assert status.diagnostic_code == "no_data"
    assert status.message == "Camera opened but did not provide a frame."
    assert capture.released is True


def test_camera_probe_reports_and_releases_an_unopenable_device() -> None:
    capture = FakeCapture(opened=False)
    service = CameraService(capture_factory=lambda _: capture)

    status = service.probe()

    assert status.available is False
    assert status.diagnostic_code == "device_unavailable"
    assert capture.released is True


def test_camera_start_releases_device_when_first_frame_is_missing() -> None:
    capture = FakeCapture(frame_ok=False, frame=None)
    service = CameraService(capture_factory=lambda _: capture)

    with pytest.raises(CameraUnavailable, match="did not provide a frame"):
        service.start()

    assert service.status().active is False
    assert service.status().diagnostic_code == "no_data"
    assert capture.released is True


def test_camera_factory_exception_is_reported_without_leaking_capture_state() -> None:
    service = CameraService(capture_factory=lambda _: (_ for _ in ()).throw(OSError("driver failure")))

    with pytest.raises(CameraUnavailable, match=r"initialization failed \(OSError\)"):
        service.start()

    assert service.status().available is False
    assert service.status().active is False
    assert service.status().diagnostic_code == "initialization_failed"


def test_camera_start_reports_unavailable_dependency(monkeypatch) -> None:
    monkeypatch.setattr("app.camera.service._load_opencv", lambda: None)
    service = CameraService()

    with pytest.raises(CameraUnavailable, match="OpenCV is not installed"):
        service.start()


def test_mediapipe_is_optional_and_not_started_implicitly(monkeypatch) -> None:
    monkeypatch.setattr("app.camera.vision._load_mediapipe", lambda: None)
    processor = MediaPipeHandsProcessor()

    assert processor.available is False
    with pytest.raises(VisionDependencyUnavailable, match="MediaPipe is not installed"):
        processor.start()


def test_mediapipe_reports_unavailable_when_hands_api_is_missing() -> None:
    processor = MediaPipeHandsProcessor(mediapipe_module=SimpleNamespace(solutions=SimpleNamespace()))

    assert processor.available is False
    with pytest.raises(VisionDependencyUnavailable, match="does not provide the Hands API"):
        processor.start()


def test_camera_status_endpoint_does_not_open_camera() -> None:
    app = create_app(Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True))

    response = TestClient(app).get("/api/camera/status")

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["available"] is None


def test_camera_routes_use_explicit_lifecycle_and_release_capture() -> None:
    capture = FakeCapture()
    service = CameraService(capture_factory=lambda _: capture)
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        camera_service=service,
        vision_processor=EmptyVision(),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    assert client.post("/api/camera/probe").json()["available"] is True
    started = client.post("/api/camera/start")
    assert started.status_code == 200
    assert started.json()["active"] is True
    stopped = client.post("/api/camera/stop")
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False
    assert capture.released is True


def test_camera_start_reports_unavailable_camera() -> None:
    service = CameraService(capture_factory=lambda _: FakeCapture(opened=False))
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        camera_service=service,
        vision_processor=MediaPipeHandsProcessor(mediapipe_module=None),
    )

    response = TestClient(app).post("/api/camera/start")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CAMERA_UNAVAILABLE"


def test_camera_start_rolls_back_when_vision_initialization_fails() -> None:
    capture = FakeCapture()
    service = CameraService(capture_factory=lambda _: capture)
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        camera_service=service,
        vision_processor=FailingVision(),  # type: ignore[arg-type]
    )

    response = TestClient(app).post("/api/camera/start")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VISION_UNAVAILABLE"
    assert capture.released is True
    assert service.status().active is False
