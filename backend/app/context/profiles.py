from __future__ import annotations

from app.context.detect import ForegroundWindow
from app.contracts.models import AppContext
from app.gestures.engine import GestureName

BROWSER_PROCESSES = frozenset({"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"})
POWERPOINT_PROCESSES = frozenset({"powerpnt.exe"})

GENERIC_GESTURES: dict[str, str] = {
    GestureName.SWIPE_LEFT.value: "NEXT_MEDIA",
    GestureName.SWIPE_RIGHT.value: "PREVIOUS_MEDIA",
    GestureName.OPEN_PALM.value: "PAUSE",
    GestureName.FIST.value: "PLAY",
    GestureName.THUMBS_UP.value: "VOLUME_UP",
    GestureName.THUMBS_DOWN.value: "VOLUME_DOWN",
    GestureName.INDEX_UP.value: "VOLUME_UP",
    GestureName.INDEX_DOWN.value: "VOLUME_DOWN",
    GestureName.TWO_FINGERS.value: "SCROLL_DOWN",
    GestureName.VOLUME_UP.value: "VOLUME_UP",
    GestureName.VOLUME_DOWN.value: "VOLUME_DOWN",
    GestureName.SCROLL.value: "SCROLL_DOWN",
}

PROFILE_GESTURES: dict[str, dict[str, str]] = {
    "youtube": {
        **GENERIC_GESTURES,
        GestureName.SWIPE_LEFT.value: "NEXT_YOUTUBE_VIDEO",
        GestureName.SWIPE_RIGHT.value: "PREVIOUS_YOUTUBE_VIDEO",
    },
    "powerpoint": {
        **GENERIC_GESTURES,
        GestureName.SWIPE_RIGHT.value: "NEXT_SLIDE",
        GestureName.SWIPE_LEFT.value: "PREVIOUS_SLIDE",
    },
    "browser": {
        **GENERIC_GESTURES,
    },
    "generic": GENERIC_GESTURES,
}

UNAVAILABLE = AppContext(application="unknown", profile="generic", available=False, label="Unknown")


def classify(window: ForegroundWindow | None) -> AppContext:
    if window is None:
        return UNAVAILABLE
    process = window.process_name.strip().casefold()
    title = window.title.casefold()
    if process in POWERPOINT_PROCESSES:
        return AppContext(application="powerpoint", profile="powerpoint", available=True, label="PowerPoint")
    if process in BROWSER_PROCESSES:
        application = "chrome" if process == "chrome.exe" else "browser"
        if "youtube" in title:
            label = "Chrome / YouTube" if application == "chrome" else "Browser / YouTube"
            return AppContext(application=application, profile="youtube", available=True, label=label)
        label = "Chrome" if application == "chrome" else "Browser"
        return AppContext(application=application, profile="browser", available=True, label=label)
    return AppContext(application="unknown", profile="generic", available=True, label="Unknown")


def gesture_intent_name(gesture: str, profile: str, direction: str | None = None) -> str | None:
    if gesture.strip().upper() == GestureName.SCROLL.value and direction in {"up", "down"}:
        return "SCROLL_UP" if direction == "up" else "SCROLL_DOWN"
    mapping = PROFILE_GESTURES.get(profile, GENERIC_GESTURES)
    return mapping.get(gesture.strip().upper())
