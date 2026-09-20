from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.database.mongodb import MongoChatSessionRepository, MongoSessionDataError


class FakeMongoClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeCollection:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document
        self.find_calls: list[tuple[object, object]] = []
        self.find_one_calls: list[tuple[object, object]] = []
        self.delete_calls: list[object] = []

    def find(self, query: object, projection: object) -> list[dict[str, object]]:
        self.find_calls.append((query, projection))
        return [self.document]

    def find_one(self, query: object, projection: object) -> dict[str, object]:
        self.find_one_calls.append((query, projection))
        return {"_id": self.document["_id"]}

    def delete_one(self, query: object) -> SimpleNamespace:
        self.delete_calls.append(query)
        return SimpleNamespace(deleted_count=1)


def test_repository_lists_revalidates_and_deletes_expired_session() -> None:
    started_at = datetime(2024, 1, 10, tzinfo=timezone.utc)
    cutoff = datetime(2025, 1, 10, tzinfo=timezone.utc)
    client = FakeMongoClient()
    collection = FakeCollection({"_id": "session-1", "iniciada_em": started_at})
    repository = MongoChatSessionRepository(
        "unused",
        "unused",
        client=client,
        collection=collection,
    )

    sessions = list(repository.list_expired(cutoff))

    assert sessions[0].session_id == "session-1"
    assert sessions[0].started_at == started_at
    assert repository.is_expired("session-1", cutoff) is True
    assert repository.delete_expired(sessions[0], cutoff) is True
    assert collection.find_calls[0][0] == {
        "iniciada_em": {"$type": "date", "$lt": cutoff}
    }
    assert collection.delete_calls[0] == {
        "_id": "session-1",
        "iniciada_em": {"$eq": started_at, "$type": "date", "$lt": cutoff},
    }

    repository.close()
    assert client.closed is True


def test_repository_rejects_non_textual_session_id() -> None:
    client = FakeMongoClient()
    collection = FakeCollection(
        {"_id": 123, "iniciada_em": datetime(2024, 1, 10, tzinfo=timezone.utc)}
    )
    repository = MongoChatSessionRepository(
        "unused",
        "unused",
        client=client,
        collection=collection,
    )

    with pytest.raises(MongoSessionDataError, match="_id textual"):
        list(repository.list_expired(datetime(2025, 1, 10, tzinfo=timezone.utc)))
