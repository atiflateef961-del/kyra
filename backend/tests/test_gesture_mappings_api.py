from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.auth.firebase import VerifiedIdentity
from app.core.config import Settings
from app.database.mongo import GestureMappingRepository
from app.main import create_app


class MappingCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    def find(self, query, projection):
        rows = [deepcopy(item) for item in self.documents if all(item.get(key) == value for key, value in query.items())]
        if projection.get("_id") is False:
            for row in rows:
                row.pop("_id", None)
        return _Cursor(rows)

    def find_one(self, query, projection):
        rows = self.find(query, projection)
        return rows[0] if rows else None

    def update_one(self, query, update, upsert):
        document = next((item for item in self.documents if all(item.get(key) == value for key, value in query.items())), None)
        if document is None:
            assert upsert
            document = {**update["$setOnInsert"]}
            self.documents.append(document)
        document.update(update["$set"])

    def delete_one(self, query):
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class _Cursor(list):
    def sort(self, key, direction):
        return _Cursor(sorted(self, key=lambda item: item.get(key, datetime.min), reverse=direction < 0))


def _settings() -> Settings:
    return Settings(app_env="development", cors_origins=("http://localhost:3000",), dry_run=True)


def _verifier(token: str) -> VerifiedIdentity:
    return VerifiedIdentity(firebase_uid=token, email=None, name=None)


def test_gesture_mapping_crud_is_owner_scoped() -> None:
    repository = GestureMappingRepository(MappingCollection())  # type: ignore[arg-type]
    client = TestClient(create_app(_settings(), token_verifier=_verifier, gesture_mapping_repository=repository))
    user_a = {"Authorization": "Bearer user-a"}
    user_b = {"Authorization": "Bearer user-b"}
    body = {"gesture": "SWIPE_RIGHT", "action": "NEXT_MEDIA", "application": "youtube", "enabled": True}

    created = client.post("/api/gestures", headers=user_a, json=body)
    assert created.status_code == 200
    mapping_id = created.json()["mapping_id"]
    assert client.get("/api/gestures", headers=user_b).json() == []

    updated = client.put(
        f"/api/gestures/{mapping_id}",
        headers=user_a,
        json={**body, "action": "NEXT_SLIDE", "application": "powerpoint"},
    )
    assert updated.status_code == 200
    assert updated.json()["action"] == "NEXT_SLIDE"
    assert client.get("/api/gestures", headers=user_a).json()[0]["application"] == "powerpoint"

    deleted = client.delete(f"/api/gestures/{mapping_id}", headers=user_a)
    assert deleted.status_code == 200
    assert client.get("/api/gestures", headers=user_a).json() == []


def test_gesture_mapping_rejects_unknown_or_dangerous_values() -> None:
    repository = GestureMappingRepository(MappingCollection())  # type: ignore[arg-type]
    client = TestClient(create_app(_settings(), token_verifier=_verifier, gesture_mapping_repository=repository))

    for body in (
        {"gesture": "UNKNOWN", "action": "PAUSE", "application": "generic", "enabled": True},
        {"gesture": "OPEN_PALM", "action": "SHUTDOWN", "application": "generic", "enabled": True},
        {"gesture": "OPEN_PALM", "action": "PAUSE", "application": "powershell", "enabled": True},
    ):
        response = client.post("/api/gestures", headers={"Authorization": "Bearer user-a"}, json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_GESTURE_MAPPING"


def test_gesture_mapping_duplicate_returns_conflict_instead_of_server_error() -> None:
    class ConflictingRepository(GestureMappingRepository):
        def upsert(self, firebase_uid, mapping_id, changes):
            raise DuplicateKeyError("duplicate mapping")

    client = TestClient(
        create_app(
            _settings(),
            token_verifier=_verifier,
            gesture_mapping_repository=ConflictingRepository(MappingCollection()),  # type: ignore[arg-type]
        )
    )
    response = client.post(
        "/api/gestures",
        headers={"Authorization": "Bearer user-a"},
        json={"gesture": "SWIPE_RIGHT", "action": "NEXT_MEDIA", "application": "youtube", "enabled": True},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GESTURE_MAPPING_CONFLICT"
