from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth.firebase import VerifiedIdentity
from app.core.config import Settings
from app.database.mongo import DeviceRepository
from app.main import create_app


class DeviceCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    def find(self, query, projection):
        rows = [deepcopy(item) for item in self.documents if all(item.get(key) == value for key, value in query.items())]
        return _Cursor(rows)

    def find_one(self, query, projection):
        rows = [deepcopy(item) for item in self.documents if all(item.get(key) == value for key, value in query.items())]
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
        return _Cursor(sorted(self, key=lambda item: item[key], reverse=direction < 0))


def _settings() -> Settings:
    return Settings(app_env="development", cors_origins=("http://localhost:3000",), dry_run=True)


def _verifier(token: str) -> VerifiedIdentity:
    return VerifiedIdentity(firebase_uid=token, email=None, name=None)


def test_device_registration_is_owner_scoped_and_removable() -> None:
    repository = DeviceRepository(DeviceCollection())  # type: ignore[arg-type]
    app = create_app(_settings(), token_verifier=_verifier, device_repository=repository)
    client = TestClient(app)

    created = client.post("/api/devices", headers={"Authorization": "Bearer user-a"}, json={"device_id": "device-1", "display_name": "Laptop"})
    assert created.status_code == 200
    assert created.json()["device_id"] == "device-1"
    assert client.get("/api/devices", headers={"Authorization": "Bearer user-a"}).json()[0]["display_name"] == "Laptop"
    assert client.get("/api/devices", headers={"Authorization": "Bearer user-b"}).json() == []

    removed = client.delete("/api/devices/device-1", headers={"Authorization": "Bearer user-a"})
    assert removed.status_code == 200
    assert client.get("/api/devices", headers={"Authorization": "Bearer user-a"}).json() == []


def test_device_registration_rejects_missing_details() -> None:
    repository = DeviceRepository(DeviceCollection())  # type: ignore[arg-type]
    client = TestClient(create_app(_settings(), token_verifier=_verifier, device_repository=repository))

    response = client.post("/api/devices", headers={"Authorization": "Bearer user-a"}, json={"display_name": "Laptop"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DEVICE"
