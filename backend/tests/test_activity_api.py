from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth.firebase import VerifiedIdentity
from app.core.config import Settings
from app.database.mongo import ActivityLogRepository
from app.main import create_app


class ActivityCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    def insert_one(self, document):
        self.documents.append(deepcopy(document))
        return SimpleNamespace(inserted_id=document["activity_id"])

    def count_documents(self, query):
        return sum(1 for item in self.documents if all(item.get(key) == value for key, value in query.items()))

    def find(self, query, projection):
        rows = [deepcopy(item) for item in self.documents if all(item.get(key) == value for key, value in query.items())]
        return _Cursor(rows)


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


def test_activity_is_written_filtered_paginated_and_owner_scoped() -> None:
    repository = ActivityLogRepository(ActivityCollection())  # type: ignore[arg-type]
    app = create_app(_settings(), token_verifier=_verifier, activity_repository=repository)
    client = TestClient(app)
    headers = {"Authorization": "Bearer user-a"}

    first = client.post("/api/commands", headers=headers, json={"identifier": "PAUSE", "parameters": {}})
    second = client.post("/api/commands", headers=headers, json={"identifier": "PLAY", "parameters": {}})
    assert first.status_code == 200
    assert second.status_code == 200

    page = client.get("/api/activity?limit=1&offset=0", headers=headers)
    filtered = client.get("/api/activity?result_status=dry_run", headers=headers)
    other = client.get("/api/activity", headers={"Authorization": "Bearer user-b"})

    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert filtered.json()["total"] == 2
    assert other.json()["total"] == 0
    assert page.json()["items"][0]["input_type"] == "command"


def test_activity_repository_rejects_missing_owner() -> None:
    repository = ActivityLogRepository(ActivityCollection())  # type: ignore[arg-type]

    try:
        repository.list(" ")
    except ValueError:
        pass
    else:
        raise AssertionError("Activity reads require a verified owner.")
