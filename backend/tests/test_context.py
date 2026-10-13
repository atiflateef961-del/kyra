from fastapi.testclient import TestClient

import ctypes
from ctypes import wintypes
from types import SimpleNamespace

from app.context.detect import ForegroundWindow, _configure_win32_signatures
from app.context.engine import ContextEngine
from app.core.config import Settings
from app.main import create_app


class FakeReader:
    def __init__(self, window: ForegroundWindow | None) -> None:
        self.window = window

    def read(self) -> ForegroundWindow | None:
        return self.window


def test_foreground_reader_declares_pointer_sized_win32_handle_types() -> None:
    def api():
        return SimpleNamespace(**{name: lambda *args: 0 for name in (
            "GetForegroundWindow", "GetWindowTextLengthW", "GetWindowTextW",
            "GetWindowThreadProcessId", "OpenProcess", "QueryFullProcessImageNameW", "CloseHandle",
        )})

    user32, kernel32 = api(), api()
    _configure_win32_signatures(user32, kernel32, ctypes, wintypes)

    assert user32.GetForegroundWindow.restype is wintypes.HWND
    assert kernel32.OpenProcess.restype is wintypes.HANDLE
    assert user32.GetWindowThreadProcessId.argtypes[0] is wintypes.HWND
    assert kernel32.CloseHandle.argtypes[0] is wintypes.HANDLE


def test_chrome_youtube_swipe_left_maps_to_next_suggested_video() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "YouTube - video")))

    resolved = engine.resolve_gesture("SWIPE_LEFT", 0.94)

    assert resolved.context.label == "Chrome / YouTube"
    assert resolved.intent is not None
    assert resolved.intent.name == "NEXT_YOUTUBE_VIDEO"
    assert resolved.intent.confidence == 0.94


def test_chrome_youtube_swipe_right_maps_to_previous_suggested_video() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "YouTube - video")))

    resolved = engine.resolve_gesture("SWIPE_RIGHT")

    assert resolved.intent is not None
    assert resolved.intent.name == "PREVIOUS_YOUTUBE_VIDEO"


def test_edge_youtube_swipe_left_maps_to_next_suggested_video() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("msedge.exe", "Video title - YouTube")))

    resolved = engine.resolve_gesture("SWIPE_LEFT")

    assert resolved.context.profile == "youtube"
    assert resolved.context.application == "browser"
    assert resolved.intent is not None
    assert resolved.intent.name == "NEXT_YOUTUBE_VIDEO"


def test_explicit_youtube_target_overrides_kyra_dashboard_browser_context() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "KYRA")))

    resolved = engine.resolve_gesture("SWIPE_LEFT", 0.94, profile_override="youtube")

    assert resolved.context.profile == "youtube"
    assert resolved.context.application == "chrome"
    assert resolved.context.label == "YouTube (selected target)"
    assert resolved.intent is not None
    assert resolved.intent.name == "NEXT_YOUTUBE_VIDEO"


def test_explicit_youtube_target_preserves_edge_application_context() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("msedge.exe", "KYRA")))

    resolved = engine.resolve_gesture("SWIPE_LEFT", profile_override="youtube")

    assert resolved.context.profile == "youtube"
    assert resolved.context.application == "browser"
    assert resolved.context.label == "YouTube (selected target)"
    assert resolved.intent is not None
    assert resolved.intent.name == "NEXT_YOUTUBE_VIDEO"


def test_thumbs_down_maps_to_volume_down_in_youtube_context() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "YouTube - video")))

    resolved = engine.resolve_gesture("THUMBS_DOWN")

    assert resolved.intent is not None
    assert resolved.intent.name == "VOLUME_DOWN"


def test_thumbs_up_maps_to_volume_up_in_youtube_context() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "YouTube - video")))

    resolved = engine.resolve_gesture("THUMBS_UP")

    assert resolved.intent is not None
    assert resolved.intent.name == "VOLUME_UP"


def test_fist_maps_to_play_in_youtube_context() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "YouTube - video")))

    resolved = engine.resolve_gesture("FIST")

    assert resolved.intent is not None
    assert resolved.intent.name == "PLAY"


def test_two_finger_scroll_uses_the_detected_direction() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("chrome.exe", "KYRA")))

    resolved = engine.resolve_gesture("SCROLL", direction="up")

    assert resolved.intent is not None
    assert resolved.intent.name == "SCROLL_UP"


def test_powerpoint_swipe_right_maps_to_next_slide() -> None:
    engine = ContextEngine(FakeReader(ForegroundWindow("POWERPNT.EXE", "Deck")))

    resolved = engine.resolve_gesture("SWIPE_RIGHT")

    assert resolved.context.profile == "powerpoint"
    assert resolved.intent is not None
    assert resolved.intent.name == "NEXT_SLIDE"


def test_missing_foreground_window_does_not_create_contextual_intent() -> None:
    resolved = ContextEngine(FakeReader(None)).resolve_gesture("SWIPE_RIGHT")

    assert resolved.context.available is False
    assert resolved.intent is None


def test_context_endpoint_returns_verified_local_classification() -> None:
    app = create_app(
        Settings(app_env="test", cors_origins=("http://localhost:3000",), dry_run=True),
        context_engine=ContextEngine(FakeReader(ForegroundWindow("POWERPNT.EXE", "Deck"))),
    )

    response = TestClient(app).get("/api/context")

    assert response.status_code == 200
    assert response.json()["profile"] == "powerpoint"
