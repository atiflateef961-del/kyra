from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth.firebase import VerifiedIdentity
from app.core.config import Settings
from app.database.mongo import NotificationRepository
from app.main import create_app


class NotificationCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    @staticmethod
    def _matches(item, query):
        for key, expected in query.items():
            if key == "dismissed" and isinstance(expected, dict) and "$ne" in expected:
                if item.get("dismissed") == expected["$ne"]:
                    return False
                continue
            if item.get(key) != expected:
                return False
        return True

    def count_documents(self, query):
        return sum(1 for item in self.documents if self._matches(item, query))

    def find(self, query, projection):
        rows = [deepcopy(item) for item in self.documents if self._matches(item, query)]
        return _Cursor(rows)

    def insert_one(self, document):
        self.documents.append(deepcopy(document))
        return SimpleNamespace(inserted_id=document["notification_id"])

    def update_one(self, query, update):
        document = next((item for item in self.documents if all(item.get(key) == value for key, value in query.items())), None)
        if document is None:
            return SimpleNamespace(matched_count=0)
        document.update(update["$set"])
        return SimpleNamespace(matched_count=1)


class _Cursor(list):
    def sort(self, key, direction):
        return _Cursor(sorted(self, key=lambda item: item[key], reverse=direction < 0))

    def skip(self, amount):
        return _Cursor(self[amount:])

    def limit(self, amount):
        return _Cursor(self[:amount])


def _settings() -> Settings:
    return Settings(app_env="development", cors_origins=("http://localhost:3000",), dry_run=True)


def _verifier(token: str) -> VerifiedIdentity:
    return VerifiedIdentity(firebase_uid=token, email=None, name=None)


def test_notifications_are_owner_scoped_and_dismissible() -> None:
    repository = NotificationRepository(NotificationCollection())  # type: ignore[arg-type]
    app = create_app(_settings(), token_verifier=_verifier, notification_repository=repository)
    client = TestClient(app)

    created = client.post(
        "/api/notifications",
        headers={"Authorization": "Bearer user-a"},
        json={"notification_id": "n-1", "title": "Sync ready", "message": "Your local sync is complete.", "severity": "info"},
    )
    assert created.status_code == 200
    inbox = client.get("/api/notifications", headers={"Authorization": "Bearer user-a"})
    other = client.get("/api/notifications", headers={"Authorization": "Bearer user-b"})
    assert len(inbox.json()) == 1
    assert other.json() == []

    dismissed = client.post("/api/notifications/n-1/dismiss", headers={"Authorization": "Bearer user-a"})
    assert dismissed.status_code == 200
    assert client.get("/api/notifications", headers={"Authorization": "Bearer user-a"}).json() == []


def test_notifications_reject_missing_payload() -> None:
    repository = NotificationRepository(NotificationCollection())  # type: ignore[arg-type]
    client = TestClient(create_app(_settings(), token_verifier=_verifier, notification_repository=repository))

    missing = client.post("/api/notifications", headers={"Authorization": "Bearer user-a"}, json={"title": "Nope"})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "INVALID_NOTIFICATION"
