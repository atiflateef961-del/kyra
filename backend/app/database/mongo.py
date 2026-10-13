from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.contracts.models import ActionStatus, ActivityLog, Device, Notification


class DatabaseUnavailable(RuntimeError):
    """Raised without connection details when MongoDB is unavailable."""


class OwnershipError(ValueError):
    """Raised when an operation has no verified user identity."""


ALLOWED_SETTINGS = frozenset({"theme", "camera_enabled", "microphone_enabled", "privacy_mode", "ai_provider"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _verified_uid(firebase_uid: str) -> str:
    uid = firebase_uid.strip()
    if not uid:
        raise OwnershipError("A verified Firebase UID is required.")
    return uid


class MongoStore:
    """Owns a real MongoDB client; no fallback database is used at runtime."""

    def __init__(self, uri: str, database_name: str = "kyra", *, client: Any | None = None) -> None:
        if not uri.strip():
            raise DatabaseUnavailable("MongoDB is not configured.")
        self._client = client or MongoClient(uri, serverSelectionTimeoutMS=3_000, connectTimeoutMS=3_000)
        self._database: Database[dict[str, Any]] = self._client[database_name]

    def connect(self) -> None:
        try:
            self._client.admin.command("ping")
            self.ensure_indexes()
        except PyMongoError as cause:
            raise DatabaseUnavailable("MongoDB is unavailable.") from cause

    def close(self) -> None:
        self._client.close()

    @property
    def settings(self) -> Collection[dict[str, Any]]:
        return self._database["settings"]

    @property
    def gesture_mappings(self) -> Collection[dict[str, Any]]:
        return self._database["gesture_mappings"]

    @property
    def activity_logs(self) -> Collection[dict[str, Any]]:
        return self._database["activity_logs"]

    @property
    def devices(self) -> Collection[dict[str, Any]]:
        return self._database["devices"]

    @property
    def notifications(self) -> Collection[dict[str, Any]]:
        return self._database["notifications"]

    def ensure_indexes(self) -> None:
        self._database["users"].create_index([("firebase_uid", ASCENDING)], unique=True, name="users_firebase_uid_unique")
        self.settings.create_index([("firebase_uid", ASCENDING)], unique=True, name="settings_firebase_uid_unique")
        self._database["gesture_mappings"].create_index(
            [("firebase_uid", ASCENDING), ("gesture", ASCENDING), ("application", ASCENDING)],
            unique=True,
            name="gesture_mapping_owner_context_unique",
        )
        self._database["gesture_mappings"].create_index(
            [("firebase_uid", ASCENDING), ("mapping_id", ASCENDING)],
            unique=True,
            name="gesture_mapping_owner_id_unique",
        )
        self._database["activity_logs"].create_index(
            [("firebase_uid", ASCENDING), ("timestamp", DESCENDING)],
            name="activity_owner_timestamp",
        )
        self._database["devices"].create_index(
            [("firebase_uid", ASCENDING), ("device_id", ASCENDING)],
            unique=True,
            name="device_owner_id_unique",
        )
        self.notifications.create_index(
            [("firebase_uid", ASCENDING), ("notification_id", ASCENDING)],
            unique=True,
            name="notification_owner_id_unique",
        )
        self.notifications.create_index(
            [("firebase_uid", ASCENDING), ("created_at", DESCENDING)],
            name="notification_owner_created_at",
        )


class UserSettingsRepository:
    """Settings CRUD that always scopes reads and writes to a verified owner."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def get(self, firebase_uid: str) -> dict[str, Any] | None:
        return self._collection.find_one({"firebase_uid": _verified_uid(firebase_uid)}, {"_id": False})

    def update(self, firebase_uid: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        uid = _verified_uid(firebase_uid)
        unknown = set(changes).difference(ALLOWED_SETTINGS)
        if unknown:
            raise ValueError(f"Unsupported settings fields: {', '.join(sorted(unknown))}")
        if not changes:
            raise ValueError("At least one settings field is required.")

        now = _utc_now()
        self._collection.update_one(
            {"firebase_uid": uid},
            {"$set": {**dict(changes), "updated_at": now}, "$setOnInsert": {"firebase_uid": uid, "created_at": now}},
            upsert=True,
        )
        updated = self.get(uid)
        if updated is None:
            raise DatabaseUnavailable("MongoDB did not return the saved settings.")
        return updated


class GestureMappingRepository:
    """Gesture mapping CRUD that always scopes reads and writes to a verified owner."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def list(self, firebase_uid: str) -> list[dict[str, Any]]:
        uid = _verified_uid(firebase_uid)
        cursor = self._collection.find({"firebase_uid": uid}, {"_id": False})
        return list(cursor.sort("updated_at", DESCENDING))

    def upsert(self, firebase_uid: str, mapping_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        uid = _verified_uid(firebase_uid)
        if not mapping_id.strip():
            raise ValueError("A mapping ID is required.")
        allowed = {"gesture", "action", "application", "enabled"}
        unknown = set(changes).difference(allowed)
        if unknown:
            raise ValueError(f"Unsupported gesture mapping fields: {', '.join(sorted(unknown))}")
        if not changes:
            raise ValueError("At least one gesture mapping field is required.")
        now = _utc_now()
        self._collection.update_one(
            {"firebase_uid": uid, "mapping_id": mapping_id},
            {"$set": {**dict(changes), "updated_at": now}, "$setOnInsert": {"firebase_uid": uid, "mapping_id": mapping_id}},
            upsert=True,
        )
        updated = self._collection.find_one({"firebase_uid": uid, "mapping_id": mapping_id}, {"_id": False})
        if updated is None:
            raise DatabaseUnavailable("MongoDB did not return the saved gesture mapping.")
        return updated

    def delete(self, firebase_uid: str, mapping_id: str) -> bool:
        uid = _verified_uid(firebase_uid)
        result = self._collection.delete_one({"firebase_uid": uid, "mapping_id": mapping_id})
        return bool(result.deleted_count)


class ActivityLogRepository:
    """Append-only activity history scoped to a verified owner."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def append(self, firebase_uid: str, activity: ActivityLog) -> None:
        uid = _verified_uid(firebase_uid)
        self._collection.insert_one({"firebase_uid": uid, **activity.model_dump(mode="python")})

    def list(
        self,
        firebase_uid: str,
        *,
        offset: int = 0,
        limit: int = 50,
        input_type: str | None = None,
        result_status: ActionStatus | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        uid = _verified_uid(firebase_uid)
        query: dict[str, Any] = {"firebase_uid": uid}
        if input_type:
            query["input_type"] = input_type
        if result_status is not None:
            query["result_status"] = result_status.value
        total = self._collection.count_documents(query)
        cursor = self._collection.find(query, {"_id": False}).sort("timestamp", DESCENDING).skip(offset).limit(limit)
        return list(cursor), total


class DeviceRepository:
    """Owner-scoped device registration and listing for the authenticated account."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def list(self, firebase_uid: str) -> list[dict[str, Any]]:
        uid = _verified_uid(firebase_uid)
        cursor = self._collection.find({"firebase_uid": uid}, {"_id": False})
        return list(cursor.sort("last_seen_at", DESCENDING))

    def upsert(self, firebase_uid: str, device_id: str, display_name: str) -> dict[str, Any]:
        uid = _verified_uid(firebase_uid)
        device_id_value = device_id.strip()
        name_value = display_name.strip()
        if not device_id_value:
            raise ValueError("A device ID is required.")
        if not name_value:
            raise ValueError("A device display name is required.")

        now = _utc_now()
        document = {
            "firebase_uid": uid,
            "device_id": device_id_value,
            "display_name": name_value,
            "registered_at": now,
            "last_seen_at": now,
        }
        self._collection.update_one(
            {"firebase_uid": uid, "device_id": device_id_value},
            {"$set": document, "$setOnInsert": {"firebase_uid": uid, "device_id": device_id_value, "registered_at": now}},
            upsert=True,
        )
        updated = self._collection.find_one({"firebase_uid": uid, "device_id": device_id_value}, {"_id": False})
        if updated is None:
            raise DatabaseUnavailable("MongoDB did not return the saved device record.")
        return updated

    def delete(self, firebase_uid: str, device_id: str) -> bool:
        uid = _verified_uid(firebase_uid)
        result = self._collection.delete_one({"firebase_uid": uid, "device_id": device_id.strip()})
        return bool(result.deleted_count)

    def register(self, firebase_uid: str, payload: Device) -> dict[str, Any]:
        return self.upsert(firebase_uid, payload.device_id, payload.display_name)


class NotificationRepository:
    """Notification inbox scoped to a verified owner."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def list(
        self,
        firebase_uid: str,
        *,
        severity: str | None = None,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        uid = _verified_uid(firebase_uid)
        query: dict[str, Any] = {"firebase_uid": uid, "dismissed": {"$ne": True}}
        if severity:
            query["severity"] = severity
        if unread_only:
            query["read"] = False

        total = self._collection.count_documents(query)
        cursor = self._collection.find(query, {"_id": False}).sort("created_at", DESCENDING).skip(offset).limit(limit)
        return list(cursor), total

    def create(self, firebase_uid: str, notification: Notification) -> dict[str, Any]:
        uid = _verified_uid(firebase_uid)
        document = {
            "firebase_uid": uid,
            **notification.model_dump(mode="python"),
            "dismissed": False,
        }
        self._collection.insert_one(document)
        return document

    def dismiss(self, firebase_uid: str, notification_id: str) -> bool:
        uid = _verified_uid(firebase_uid)
        result = self._collection.update_one(
            {"firebase_uid": uid, "notification_id": notification_id},
            {"$set": {"dismissed": True, "read": True, "updated_at": _utc_now()}},
        )
        return bool(result.matched_count)

    def mark_read(self, firebase_uid: str, notification_id: str) -> bool:
        uid = _verified_uid(firebase_uid)
        result = self._collection.update_one(
            {"firebase_uid": uid, "notification_id": notification_id},
            {"$set": {"read": True, "updated_at": _utc_now()}},
        )
        return bool(result.matched_count)
