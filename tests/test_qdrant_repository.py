from types import SimpleNamespace

import pytest

from src.database.qdrant import QdrantDeleteError, QdrantSessionVectorRepository


class FakeQdrantClient:
    def __init__(self, count: int, status: str = "completed") -> None:
        self.result_count = count
        self.status = status
        self.count_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.closed = False

    def count(self, **kwargs: object) -> SimpleNamespace:
        self.count_calls.append(kwargs)
        return SimpleNamespace(count=self.result_count)

    def delete(self, **kwargs: object) -> SimpleNamespace:
        self.delete_calls.append(kwargs)
        return SimpleNamespace(status=self.status)

    def close(self) -> None:
        self.closed = True


def test_repository_deletes_points_filtered_by_session_id() -> None:
    client = FakeQdrantClient(count=2)
    repository = QdrantSessionVectorRepository(
        "unused",
        "unused",
        "memoria_resumos",
        client=client,
    )

    removed = repository.delete_by_session_id("session-1")

    assert removed == 2
    count_filter = client.count_calls[0]["count_filter"]
    assert count_filter.must[0].key == "session_id"
    assert count_filter.must[0].match.value == "session-1"
    assert client.count_calls[0]["exact"] is True
    assert client.delete_calls[0]["wait"] is True
    assert client.delete_calls[0]["collection_name"] == "memoria_resumos"

    repository.close()
    assert client.closed is True


def test_repository_sends_idempotent_delete_when_session_has_no_points() -> None:
    client = FakeQdrantClient(count=0)
    repository = QdrantSessionVectorRepository("unused", "unused", client=client)

    assert repository.delete_by_session_id("session-without-points") == 0
    assert len(client.delete_calls) == 1
    assert client.delete_calls[0]["wait"] is True


def test_repository_rejects_unconfirmed_qdrant_delete() -> None:
    client = FakeQdrantClient(count=1, status="acknowledged")
    repository = QdrantSessionVectorRepository("unused", "unused", client=client)

    with pytest.raises(QdrantDeleteError, match="não confirmou"):
        repository.delete_by_session_id("session-1")
