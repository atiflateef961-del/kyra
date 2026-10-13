from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import os
import subprocess
import ctypes
from ctypes import wintypes
from typing import Protocol

from app.computer.audio import AudioEndpointError, WindowsCoreAudioVolume
from app.computer.media import MediaSessionError, WindowsMediaSessionControl
from app.context.detect import ForegroundReader, WindowsForegroundReader
from app.context.profiles import classify
from app.contracts.models import ActionResult, ActionStatus


class ControllerAction(StrEnum):
    PLAY = "PLAY"
    PAUSE = "PAUSE"
    NEXT_MEDIA = "NEXT_MEDIA"
    PREVIOUS_MEDIA = "PREVIOUS_MEDIA"
    NEXT_YOUTUBE_VIDEO = "NEXT_YOUTUBE_VIDEO"
    PREVIOUS_YOUTUBE_VIDEO = "PREVIOUS_YOUTUBE_VIDEO"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    SCROLL_UP = "SCROLL_UP"
    SCROLL_DOWN = "SCROLL_DOWN"
    GO_BACK = "GO_BACK"
    GO_FORWARD = "GO_FORWARD"
    NEXT_SLIDE = "NEXT_SLIDE"
    PREVIOUS_SLIDE = "PREVIOUS_SLIDE"
    OPEN_APPLICATION = "OPEN_APPLICATION"


class ControllerError(RuntimeError):
    """Raised for a rejected or unavailable controlled action."""


ALLOWED_APPLICATIONS: dict[str, str] = {
    "chrome": "chrome.exe",
    "powerpoint": "POWERPNT.EXE",
}


class WindowsExecutor(Protocol):
    def control_media(self, action: str) -> None: ...
    def press_virtual_key(self, key_code: int) -> None: ...
    def press_key_combo(self, key_codes: tuple[int, ...]) -> None: ...
    def scroll(self, delta: int) -> None: ...
    def adjust_volume(self, delta: float) -> tuple[float, float]: ...
    def launch(self, executable: str) -> None: ...


class _KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("virtual_key", wintypes.WORD),
        ("scan_code", wintypes.WORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", ctypes.c_size_t),
    )


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("data", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("keyboard", _KeyboardInput), ("mouse", _MouseInput))


class _Input(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = (("type", wintypes.DWORD), ("payload", _InputUnion))


class NativeWindowsExecutor:
    """Dispatches fixed Windows keyboard and wheel input without invoking a shell."""

    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _KEY_UP = 0x0002
    _MOUSE_WHEEL = 0x0800

    def __init__(self) -> None:
        if os.name != "nt":
            raise ControllerError("Windows computer control is only available on Windows.")
        self._user32 = ctypes.windll.user32
        self._user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(_Input),
            ctypes.c_int,
        )
        self._user32.SendInput.restype = wintypes.UINT
        self._audio_volume = WindowsCoreAudioVolume()
        self._media_control = WindowsMediaSessionControl()

    def control_media(self, action: str) -> None:
        try:
            self._media_control.control(action)
        except MediaSessionError as cause:
            raise ControllerError(str(cause)) from cause

    def press_virtual_key(self, key_code: int) -> None:
        self._send_inputs((self._keyboard_event(key_code), self._keyboard_event(key_code, self._KEY_UP)))

    def press_key_combo(self, key_codes: tuple[int, ...]) -> None:
        events = tuple(self._keyboard_event(key_code) for key_code in key_codes)
        releases = tuple(self._keyboard_event(key_code, self._KEY_UP) for key_code in reversed(key_codes))
        self._send_inputs((*events, *releases))

    def scroll(self, delta: int) -> None:
        event = _Input(
            type=self._INPUT_MOUSE,
            mouse=_MouseInput(data=delta & 0xFFFFFFFF, flags=self._MOUSE_WHEEL),
        )
        self._send_inputs((event,))

    def adjust_volume(self, delta: float) -> tuple[float, float]:
        try:
            return self._audio_volume.adjust_volume(delta)
        except AudioEndpointError as cause:
            raise ControllerError(str(cause)) from cause

    @classmethod
    def _keyboard_event(cls, key_code: int, flags: int = 0) -> _Input:
        return _Input(
            type=cls._INPUT_KEYBOARD,
            keyboard=_KeyboardInput(virtual_key=key_code, flags=flags),
        )

    def _send_inputs(self, events: tuple[_Input, ...]) -> None:
        inputs = (_Input * len(events))(*events)
        sent = self._user32.SendInput(len(events), inputs, ctypes.sizeof(_Input))
        if sent != len(events):
            raise ControllerError("Windows did not accept all requested input events.")

    def launch(self, executable: str) -> None:
        # `executable` is selected from ALLOWED_APPLICATIONS, never user input.
        subprocess.Popen([executable], shell=False, close_fds=True)


@dataclass(frozen=True)
class ControllerCommand:
    action: ControllerAction
    action_id: str
    application: str | None = None


class ComputerController:
    """Executes a narrow action set after an upstream safety layer approves it."""

    _KEYS = {
        ControllerAction.NEXT_MEDIA: 0xB0,
        ControllerAction.PREVIOUS_MEDIA: 0xB1,
        ControllerAction.GO_BACK: 0xA6,
        ControllerAction.GO_FORWARD: 0xA7,
        ControllerAction.NEXT_SLIDE: 0x27,
        ControllerAction.PREVIOUS_SLIDE: 0x25,
    }
    _KEY_COMBOS = {
        # Use Windows media-session keys so the active YouTube tab can respond
        # while KYRA remains the foreground page for camera and voice capture.
        ControllerAction.NEXT_YOUTUBE_VIDEO: (0xB0,),
        ControllerAction.PREVIOUS_YOUTUBE_VIDEO: (0xB1,),
    }

    def __init__(
        self,
        *,
        dry_run: bool = True,
        executor: WindowsExecutor | None = None,
        foreground_reader: ForegroundReader | None = None,
    ) -> None:
        self._dry_run = dry_run
        self._executor = executor
        self._foreground_reader = foreground_reader or WindowsForegroundReader()

    def execute(self, command: ControllerCommand) -> ActionResult:
        self._validate(command)
        if self._dry_run:
            target = f"({command.application})" if command.action == ControllerAction.OPEN_APPLICATION else ""
            return self._result(command, ActionStatus.DRY_RUN, f"[DRY RUN] Would execute {command.action.value}{target}.")

        try:
            executor = self._executor or NativeWindowsExecutor()
            if command.action == ControllerAction.VOLUME_UP:
                before, after = executor.adjust_volume(0.05)
                message = f"Windows output volume changed from {before:.0%} to {after:.0%}."
            elif command.action == ControllerAction.VOLUME_DOWN:
                before, after = executor.adjust_volume(-0.05)
                message = f"Windows output volume changed from {before:.0%} to {after:.0%}."
            elif command.action in {ControllerAction.PLAY, ControllerAction.PAUSE}:
                playback_action = command.action.value.casefold()
                executor.control_media(playback_action)
                message = f"Windows media session accepted the {playback_action} request."
            elif command.action in self._KEYS:
                executor.press_virtual_key(self._KEYS[command.action])
            elif command.action in self._KEY_COMBOS:
                if command.action in {ControllerAction.NEXT_YOUTUBE_VIDEO, ControllerAction.PREVIOUS_YOUTUBE_VIDEO} and self._youtube_is_foreground():
                    key = 0x4E if command.action == ControllerAction.NEXT_YOUTUBE_VIDEO else 0x50
                    executor.press_key_combo((0x10, key))  # YouTube's documented Shift+N / Shift+P shortcuts.
                else:
                    executor.press_key_combo(self._KEY_COMBOS[command.action])
            elif command.action == ControllerAction.SCROLL_UP:
                executor.scroll(120)
            elif command.action == ControllerAction.SCROLL_DOWN:
                executor.scroll(-120)
            elif command.action == ControllerAction.OPEN_APPLICATION:
                assert command.application is not None
                executor.launch(ALLOWED_APPLICATIONS[command.application])
            else:
                raise ControllerError("Action is not implemented by the controller.")
        except ControllerError as cause:
            return self._result(command, ActionStatus.FAILED, str(cause))
        except Exception:
            return self._result(command, ActionStatus.FAILED, "The controlled local action could not be completed.")
        return self._result(
            command,
            ActionStatus.SUCCEEDED,
            message if command.action in {ControllerAction.VOLUME_UP, ControllerAction.VOLUME_DOWN, ControllerAction.PLAY, ControllerAction.PAUSE}
            else "Windows accepted the requested input; the target application's response was not verified.",
        )

    @staticmethod
    def _validate(command: ControllerCommand) -> None:
        if not isinstance(command.action, ControllerAction):
            raise ControllerError("Action is not in the local allowlist.")
        if not command.action_id.strip():
            raise ControllerError("A non-empty action ID is required.")
        if command.action == ControllerAction.OPEN_APPLICATION:
            if command.application not in ALLOWED_APPLICATIONS:
                raise ControllerError("Application is not in the local allowlist.")
        elif command.application is not None:
            raise ControllerError("Only OPEN_APPLICATION accepts an application parameter.")

    def _youtube_is_foreground(self) -> bool:
        try:
            return classify(self._foreground_reader.read()).profile == "youtube"
        except Exception:
            return False

    @staticmethod
    def _result(command: ControllerCommand, status: ActionStatus, message: str) -> ActionResult:
        return ActionResult(action_id=command.action_id, status=status, completed_at=datetime.now(UTC), message=message)
