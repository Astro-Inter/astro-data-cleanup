from __future__ import annotations

from collections.abc import Iterable
from types import TracebackType

from src.database.postgres import (
    FIREBASE_UID_EXISTS_QUERY,
    LIST_FIREBASE_UIDS_QUERY,
    PostgresAccountRepository,
)


class FakeCursor:
    def __init__(self, results: Iterable[list[tuple[object, ...]]]) -> None:
        self._results = iter(results)
        self._current: list[tuple[object, ...]] = []
        self.executions: list[tuple[str, tuple[str, ...] | None]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, query: str, params: tuple[str, ...] | None = None) -> None:
        self.executions.append((query, params))
        self._current = next(self._results)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._current

    def fetchone(self) -> tuple[object, ...] | None:
        return self._current[0] if self._current else None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def test_repository_lists_uids_and_revalidates_with_parameter() -> None:
    cursor = FakeCursor([[('uid-1',), ('uid-2',), (None,)], [(True,)]])
    connection = FakeConnection(cursor)
    repository = PostgresAccountRepository("unused", connection=connection)

    assert repository.list_firebase_uids() == {"uid-1", "uid-2"}
    assert repository.firebase_uid_exists("uid-3") is True
    assert cursor.executions == [
        (LIST_FIREBASE_UIDS_QUERY, None),
        (FIREBASE_UID_EXISTS_QUERY, ("uid-3",)),
    ]

    repository.close()
    assert connection.closed is True
