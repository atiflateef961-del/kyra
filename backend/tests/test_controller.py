import pytest

from app.computer import controller as controller_module
from app.computer.controller import ComputerController, ControllerAction, ControllerCommand, ControllerError, NativeWindowsExecutor
from app.contracts.models import ActionStatus
from app.context.detect import ForegroundWindow


class RecordingExecutor:
    """Explicit test executor; it has no operating-system side effects."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

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


class FakeForegroundReader:
    def __init__(self, window: ForegroundWindow | None) -> None:
        self.window = window

    def read(self) -> ForegroundWindow | None:
        return self.window


def test_dry_run_never_calls_the_executor() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(dry_run=True, executor=executor)

    result = controller.execute(ControllerCommand(ControllerAction.NEXT_MEDIA, "action-1"))

    assert result.status == ActionStatus.DRY_RUN
    assert executor.calls == []


def test_non_dry_run_uses_verified_endpoint_volume_control() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(dry_run=False, executor=executor)

    result = controller.execute(ControllerCommand(ControllerAction.VOLUME_UP, "action-2"))

    assert result.status == ActionStatus.SUCCEEDED
    assert executor.calls == [("volume", 0.05)]
    assert result.message == "Windows output volume changed from 50% to 55%."


def test_volume_down_uses_the_verified_endpoint_volume_control() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(dry_run=False, executor=executor)

    result = controller.execute(ControllerCommand(ControllerAction.VOLUME_DOWN, "action-volume-down"))

    assert result.status == ActionStatus.SUCCEEDED
    assert executor.calls == [("volume", -0.05)]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (ControllerAction.PLAY, ("media", "play")),
        (ControllerAction.PAUSE, ("media", "pause")),
        (ControllerAction.NEXT_MEDIA, ("key", 0xB0)),
        (ControllerAction.PREVIOUS_MEDIA, ("key", 0xB1)),
        (ControllerAction.NEXT_YOUTUBE_VIDEO, ("combo", (0xB0,))),
        (ControllerAction.PREVIOUS_YOUTUBE_VIDEO, ("combo", (0xB1,))),
        (ControllerAction.VOLUME_UP, ("volume", 0.05)),
        (ControllerAction.VOLUME_DOWN, ("volume", -0.05)),
        (ControllerAction.SCROLL_UP, ("scroll", 120)),
        (ControllerAction.SCROLL_DOWN, ("scroll", -120)),
        (ControllerAction.GO_BACK, ("key", 0xA6)),
        (ControllerAction.GO_FORWARD, ("key", 0xA7)),
    ],
)
def test_supported_media_and_navigation_actions_dispatch_fixed_input(action, expected) -> None:
    executor = RecordingExecutor()
    controller = ComputerController(dry_run=False, executor=executor)

    result = controller.execute(ControllerCommand(action, f"action-{action.value}"))

    assert result.status == ActionStatus.SUCCEEDED
    assert executor.calls == [expected]


class FakeSendInput:
    def __init__(self, accepted: int | None = None) -> None:
        self.accepted = accepted
        self.calls: list[tuple[list[controller_module._Input], int]] = []

    def __call__(self, count, inputs, input_size):
        self.calls.append(([inputs[index] for index in range(count)], input_size))
        return count if self.accepted is None else self.accepted


def _native_executor_with_fake_input(accepted: int | None = None) -> tuple[NativeWindowsExecutor, FakeSendInput]:
    executor = NativeWindowsExecutor.__new__(NativeWindowsExecutor)
    send_input = FakeSendInput(accepted)
    executor._user32 = type("FakeUser32", (), {"SendInput": send_input})()
    return executor, send_input


def test_native_executor_sends_balanced_virtual_key_events() -> None:
    executor, api = _native_executor_with_fake_input()

    executor.press_virtual_key(0xAF)

    events, input_size = api.calls[0]
    assert input_size == controller_module.ctypes.sizeof(controller_module._Input)
    assert [(event.type, event.keyboard.virtual_key, event.keyboard.flags) for event in events] == [
        (1, 0xAF, 0),
        (1, 0xAF, NativeWindowsExecutor._KEY_UP),
    ]


def test_native_executor_sends_combo_and_signed_wheel_events() -> None:
    executor, api = _native_executor_with_fake_input()

    executor.press_key_combo((0x10, 0x4E))
    executor.scroll(-120)

    combo, _ = api.calls[0]
    assert [(event.keyboard.virtual_key, event.keyboard.flags) for event in combo] == [
        (0x10, 0),
        (0x4E, 0),
        (0x4E, NativeWindowsExecutor._KEY_UP),
        (0x10, NativeWindowsExecutor._KEY_UP),
    ]
    wheel = api.calls[1][0][0]
    assert wheel.type == 0
    assert wheel.mouse.flags == NativeWindowsExecutor._MOUSE_WHEEL
    assert wheel.mouse.data == 0xFFFFFF88


def test_native_executor_rejects_partial_windows_input_dispatch() -> None:
    executor, _ = _native_executor_with_fake_input(accepted=1)

    with pytest.raises(ControllerError, match="did not accept all"):
        executor.press_virtual_key(0xAF)

    controller = ComputerController(dry_run=False, executor=executor)
    result = controller.execute(ControllerCommand(ControllerAction.NEXT_MEDIA, "action-partial-input"))

    assert result.status == ActionStatus.FAILED
    assert "did not accept all requested input" in result.message


def test_youtube_next_video_uses_the_system_media_session() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(
        dry_run=False,
        executor=executor,
        foreground_reader=FakeForegroundReader(ForegroundWindow("chrome.exe", "YouTube - video")),
    )

    result = controller.execute(ControllerCommand(ControllerAction.NEXT_YOUTUBE_VIDEO, "action-youtube"))

    assert result.status == ActionStatus.SUCCEEDED
    assert executor.calls == [("combo", (0x10, 0x4E))]


def test_youtube_previous_video_uses_the_system_media_session() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(
        dry_run=False,
        executor=executor,
        foreground_reader=FakeForegroundReader(ForegroundWindow("msedge.exe", "YouTube - video")),
    )

    result = controller.execute(ControllerCommand(ControllerAction.PREVIOUS_YOUTUBE_VIDEO, "action-youtube-previous"))

    assert result.status == ActionStatus.SUCCEEDED
    assert executor.calls == [("combo", (0x10, 0x50))]


def test_youtube_navigation_uses_global_media_key_when_youtube_is_not_foreground() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(
        dry_run=False,
        executor=executor,
        foreground_reader=FakeForegroundReader(ForegroundWindow("chrome.exe", "KYRA")),
    )

    controller.execute(ControllerCommand(ControllerAction.NEXT_YOUTUBE_VIDEO, "action-background-youtube"))

    assert executor.calls == [("combo", (0xB0,))]


def test_application_launch_rejects_unallowlisted_names() -> None:
    controller = ComputerController(dry_run=True)

    with pytest.raises(ControllerError, match="allowlist"):
        controller.execute(ControllerCommand(ControllerAction.OPEN_APPLICATION, "action-3", application="powershell"))


def test_application_launch_uses_a_fixed_executable_mapping() -> None:
    executor = RecordingExecutor()
    controller = ComputerController(dry_run=False, executor=executor)

    controller.execute(ControllerCommand(ControllerAction.OPEN_APPLICATION, "action-4", application="chrome"))

    assert executor.calls == [("launch", "chrome.exe")]


def test_dry_run_reports_the_allowlisted_application() -> None:
    controller = ComputerController(dry_run=True)

    result = controller.execute(ControllerCommand(ControllerAction.OPEN_APPLICATION, "action-4b", application="chrome"))

    assert result.status == ActionStatus.DRY_RUN
    assert result.message == "[DRY RUN] Would execute OPEN_APPLICATION(chrome)."


def test_controller_rejects_raw_action_values_even_in_dry_run() -> None:
    controller = ComputerController(dry_run=True)

    with pytest.raises(ControllerError, match="allowlist"):
        controller.execute(ControllerCommand("POWERSHELL", "action-5"))  # type: ignore[arg-type]
