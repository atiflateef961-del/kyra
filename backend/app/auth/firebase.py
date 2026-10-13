"""Firebase Admin token verification for protected FastAPI routes.

This module deliberately does not trust a browser-provided UID. Route middleware
must pass the bearer token to ``verify_id_token`` and use only its verified UID.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


class FirebaseConfigurationError(RuntimeError):
    """Raised when server-only Firebase Admin configuration is incomplete."""


class InvalidAuthenticationToken(PermissionError):
    """Raised when Firebase rejects a presented bearer token."""


class FirebaseVerificationError(RuntimeError):
    """Raised when Firebase Admin cannot verify a token due to a service error."""

    def __init__(self, error_type: str) -> None:
        super().__init__("Firebase token verification is temporarily unavailable.")
        self.error_type = error_type


@dataclass(frozen=True)
class VerifiedIdentity:
    firebase_uid: str
    email: str | None
    name: str | None


def _required_environment() -> dict[str, str]:
    names = ("FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL", "FIREBASE_PRIVATE_KEY")
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise FirebaseConfigurationError(f"Missing Firebase Admin configuration: {', '.join(missing)}")
    return values


def _firebase_admin_auth() -> Any:
    try:
        import firebase_admin
        from firebase_admin import auth, credentials
    except ImportError as cause:
        raise FirebaseConfigurationError("firebase-admin is not installed for the local agent.") from cause

    configuration = _required_environment()
    try:
        firebase_admin.get_app()
    except ValueError:
        credentials_data = {
            "type": "service_account",
            "project_id": configuration["FIREBASE_PROJECT_ID"],
            "client_email": configuration["FIREBASE_CLIENT_EMAIL"],
            "private_key": configuration["FIREBASE_PRIVATE_KEY"].replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        firebase_admin.initialize_app(credentials.Certificate(credentials_data))
    return auth


def verify_id_token(id_token: str) -> VerifiedIdentity:
    """Verify a Firebase bearer token and return only trusted identity fields."""
    if not id_token or not id_token.strip():
        raise InvalidAuthenticationToken("Authentication token is required.")

    try:
        auth = _firebase_admin_auth()
    except FirebaseConfigurationError:
        raise
    except Exception as cause:
        raise FirebaseVerificationError(type(cause).__name__) from cause

    try:
        decoded = auth.verify_id_token(id_token, check_revoked=True)
    except (auth.InvalidIdTokenError, auth.UserDisabledError, auth.UserNotFoundError) as cause:
        raise InvalidAuthenticationToken("Authentication token is invalid, expired, or revoked.") from cause
    except Exception as cause:
        # Do not turn network, certificate, permissions, or unexpected Admin SDK
        # failures into a 401. Callers log only this safe exception type.
        raise FirebaseVerificationError(type(cause).__name__) from cause

    uid = decoded.get("uid")
    if not isinstance(uid, str) or not uid:
        raise InvalidAuthenticationToken("Authentication token has no valid subject.")
    return VerifiedIdentity(
        firebase_uid=uid,
        email=decoded.get("email") if isinstance(decoded.get("email"), str) else None,
        name=decoded.get("name") if isinstance(decoded.get("name"), str) else None,
    )
