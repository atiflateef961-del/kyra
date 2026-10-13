from __future__ import annotations

from dataclasses import dataclass

from app.contracts.models import RiskLevel

LOW_ACTIONS = (
    "PLAY",
    "PAUSE",
    "NEXT_MEDIA",
    "PREVIOUS_MEDIA",
    "NEXT_YOUTUBE_VIDEO",
    "PREVIOUS_YOUTUBE_VIDEO",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "SCROLL_UP",
    "SCROLL_DOWN",
    "GO_BACK",
    "GO_FORWARD",
    "NEXT_SLIDE",
    "PREVIOUS_SLIDE",
    "OPEN_APPLICATION",
)

BLOCKED_HIGH_ACTIONS = (
    "DELETE_FILE",
    "SEND_EMAIL",
    "PURCHASE",
    "INSTALL_SOFTWARE",
    "CHANGE_SYSTEM_SETTINGS",
    "SHUTDOWN",
)


@dataclass(frozen=True)
class ActionDefinition:
    identifier: str
    description: str
    risk_level: RiskLevel
    requires_confirmation: bool
    executable: bool
    allowed_parameters: frozenset[str]


def _low(identifier: str, description: str, parameters: frozenset[str] = frozenset()) -> ActionDefinition:
    return ActionDefinition(
        identifier=identifier,
        description=description,
        risk_level=RiskLevel.LOW,
        requires_confirmation=False,
        executable=True,
        allowed_parameters=parameters,
    )


def _blocked(identifier: str, description: str) -> ActionDefinition:
    return ActionDefinition(
        identifier=identifier,
        description=description,
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
        executable=False,
        allowed_parameters=frozenset(),
    )


ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "PLAY": _low("PLAY", "Play media"),
    "PAUSE": _low("PAUSE", "Pause media"),
    "NEXT_MEDIA": _low("NEXT_MEDIA", "Next media item"),
    "PREVIOUS_MEDIA": _low("PREVIOUS_MEDIA", "Previous media item"),
    "NEXT_YOUTUBE_VIDEO": _low("NEXT_YOUTUBE_VIDEO", "Open the next suggested YouTube video"),
    "PREVIOUS_YOUTUBE_VIDEO": _low("PREVIOUS_YOUTUBE_VIDEO", "Open the previous YouTube video"),
    "VOLUME_UP": _low("VOLUME_UP", "Increase volume"),
    "VOLUME_DOWN": _low("VOLUME_DOWN", "Decrease volume"),
    "SCROLL_UP": _low("SCROLL_UP", "Scroll up"),
    "SCROLL_DOWN": _low("SCROLL_DOWN", "Scroll down"),
    "GO_BACK": _low("GO_BACK", "Go back"),
    "GO_FORWARD": _low("GO_FORWARD", "Go forward"),
    "NEXT_SLIDE": _low("NEXT_SLIDE", "Next presentation slide"),
    "PREVIOUS_SLIDE": _low("PREVIOUS_SLIDE", "Previous presentation slide"),
    "OPEN_APPLICATION": _low("OPEN_APPLICATION", "Open an allowlisted application", frozenset({"application"})),
    "DELETE_FILE": _blocked("DELETE_FILE", "Delete a file"),
    "SEND_EMAIL": _blocked("SEND_EMAIL", "Send email"),
    "PURCHASE": _blocked("PURCHASE", "Make a purchase"),
    "INSTALL_SOFTWARE": _blocked("INSTALL_SOFTWARE", "Install software"),
    "CHANGE_SYSTEM_SETTINGS": _blocked("CHANGE_SYSTEM_SETTINGS", "Change system settings"),
    "SHUTDOWN": _blocked("SHUTDOWN", "Shut down the computer"),
}


def get_definition(identifier: str) -> ActionDefinition | None:
    return ACTION_REGISTRY.get(identifier)
