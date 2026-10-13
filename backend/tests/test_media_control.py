from types import SimpleNamespace

import pytest

from app.computer.media import MediaSessionError, WindowsMediaSessionControl


class FakeSession:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.requests: list[str] = []

    async def try_play_async(self) -> bool:
        self.requests.append("play")
        return self.accepted

    async def try_pause_async(self) -> bool:
        self.requests.append("pause")
        return self.accepted


def fake_module(session: FakeSession | None):
    class Manager:
        @classmethod
        async def request_async(cls):
            return cls()

        def get_current_session(self):
            return session

    return SimpleNamespace(
        GlobalSystemMediaTransportControlsSessionManager=Manager,
    )


@pytest.mark.parametrize("action", ("play", "pause"))
def test_media_control_uses_distinct_non_toggle_session_requests(action: str) -> None:
    session = FakeSession()
    control = WindowsMediaSessionControl(module=fake_module(session), platform="nt")

    control.control(action)

    assert session.requests == [action]


def test_media_control_fails_when_no_session_is_active() -> None:
    control = WindowsMediaSessionControl(module=fake_module(None), platform="nt")

    with pytest.raises(MediaSessionError, match="No active Windows media session"):
        control.control("play")


def test_media_control_fails_when_session_rejects_the_request() -> None:
    session = FakeSession(accepted=False)
    control = WindowsMediaSessionControl(module=fake_module(session), platform="nt")

    with pytest.raises(MediaSessionError, match="did not accept the pause request"):
        control.control("pause")


def test_media_control_rejects_unknown_actions() -> None:
    control = WindowsMediaSessionControl(module=fake_module(FakeSession()), platform="nt")

    with pytest.raises(MediaSessionError, match="not supported"):
        control.control("toggle")


def test_media_control_reports_unavailable_windows_service_safely() -> None:
    class UnavailableManager:
        @classmethod
        async def request_async(cls):
            raise OSError(-2147023836, "service detail")

    module = SimpleNamespace(GlobalSystemMediaTransportControlsSessionManager=UnavailableManager)
    control = WindowsMediaSessionControl(module=module, platform="nt")

    with pytest.raises(MediaSessionError, match="service is unavailable") as error:
        control.control("play")
    assert "service detail" not in str(error.value)
