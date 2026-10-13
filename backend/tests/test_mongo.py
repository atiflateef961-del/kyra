"""Unit tests use an explicit in-memory collection, never a real MongoDB server."""

from copy import deepcopy
from typing import Any

import pytest
from pymongo.errors import PyMongoError

from app.database.mongo import DatabaseUnavailable, MongoStore, OwnershipError, UserSettingsRepository


class InMemoryCollection:
    """Minimal test double for repository behavior; not used by the application."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def find_one(self, query: dict[str, str], projection: dict[str, bool]) -> dict[str, Any] | None:
        document = self.documents.get(query["firebase_uid"])
        if document is None:
            return None
        result = deepcopy(document)
        if projection.get("_id") is False:
            result.pop("_id", None)
        return result

    def update_one(self, query: dict[str, str], update: dict[str, dict[str, Any]], upsert: bool) -> None:
        uid = query["firebase_uid"]
        existing = self.documents.get(uid)
        if existing is None:
            assert upsert
            existing = {"_id": uid, **update["$setOnInsert"]}
            self.documents[uid] = existing
        existing.update(update["$set"])


class IndexCollection:
    def __init__(self) -> None:
        self.indexes: list[str] = []

    def create_index(self, keys: object, *, name: str, **_: object) -> None:
        self.indexes.append(name)


class InMemoryDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, IndexCollection] = {}

    def __getitem__(self, name: str) -> IndexCollection:
        return self.collections.setdefault(name, IndexCollection())


class InMemoryAdmin:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails
        self.pinged = False

    def command(self, name: str) -> None:
        assert name == "ping"
        if self.fails:
            raise PyMongoError("test connection failure")
        self.pinged = True


class InMemoryMongoClient:
    def __init__(self, fails: bool = False) -> None:
        self.admin = InMemoryAdmin(fails)
        self.database = InMemoryDatabase()

    def __getitem__(self, name: str) -> InMemoryDatabase:
        assert name == "kyra"
        return self.database

    def close(self) -> None:
        pass


def test_settings_upsert_is_scoped_to_the_verified_user() -> None:
    repository = UserSettingsRepository(InMemoryCollection())  # type: ignore[arg-type]

    repository.update("user-a", {"theme": "dark", "privacy_mode": True})
    repository.update("user-b", {"theme": "light"})

    assert repository.get("user-a")["theme"] == "dark"
    assert repository.get("user-b")["theme"] == "light"
    assert repository.get("user-a")["privacy_mode"] is True


def test_settings_reject_unverified_owner_and_unknown_fields() -> None:
    repository = UserSettingsRepository(InMemoryCollection())  # type: ignore[arg-type]

    with pytest.raises(OwnershipError):
        repository.get(" ")
    with pytest.raises(ValueError, match="Unsupported"):
        repository.update("user-a", {"firebase_uid": "user-b"})


def test_connect_pings_and_creates_ownership_indexes() -> None:
    client = InMemoryMongoClient()
    store = MongoStore("mongodb://test", client=client)

    store.connect()

    assert client.admin.pinged is True
    assert "settings_firebase_uid_unique" in client.database["settings"].indexes
    assert "activity_owner_timestamp" in client.database["activity_logs"].indexes
    assert "notification_owner_id_unique" in client.database["notifications"].indexes
    assert "notification_owner_created_at" in client.database["notifications"].indexes


def test_connection_failure_does_not_expose_connection_details() -> None:
    with pytest.raises(DatabaseUnavailable, match="MongoDB is unavailable"):
        MongoStore("mongodb://private-host", client=InMemoryMongoClient(fails=True)).connect()
