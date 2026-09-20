from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

import pytest

from src.config.settings import Settings
from src.database.mongodb import ChatSession
from src.workers.chatbot_sessions.worker import (
    ChatbotSessionCleanupError,
    ChatbotSessionsWorker,
    one_calendar_year_before,
)


class FakeSessionRepository:
    def __init__(
        self,
        sessions: Iterable[ChatSession],
        *,
        revalidated: set[str] | None = None,
        delete_results: dict[str, bool] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._sessions = tuple(sessions)
        self._revalidated = (
            revalidated
            if revalidated is not None
            else {session.session_id for session in self._sessions}
        )
        self._delete_results = delete_results or {}
        self.events = events if events is not None else []
        self.closed = False

    def list_expired(self, cutoff: datetime) -> Iterable[ChatSession]:
        self.events.append("mongo:list")
        return iter(self._sessions)

    def is_expired(self, session_id: str, cutoff: datetime) -> bool:
        self.events.append(f"mongo:revalidate:{session_id}")
        return session_id in self._revalidated

    def delete_expired(self, session: ChatSession, cutoff: datetime) -> bool:
        self.events.append(f"mongo:delete:{session.session_id}")
        return self._delete_results.get(session.session_id, True)

    def close(self) -> None:
        self.closed = True


class FakeVectorRepository:
    def __init__(
        self,
        points: dict[str, int],
        *,
        failing_sessions: set[str] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._points = points
        self._failing_sessions = failing_sessions or set()
        self.events = events if events is not None else []
        self.closed = False

    def count_by_session_id(self, session_id: str) -> int:
        self.events.append(f"qdrant:count:{session_id}")
        if session_id in self._failing_sessions:
            raise RuntimeError("qdrant unavailable")
        return self._points.get(session_id, 0)

    def delete_by_session_id(self, session_id: str) -> int:
        self.events.append(f"qdrant:delete:{session_id}")
        if session_id in self._failing_sessions:
            raise RuntimeError("qdrant unavailable")
        return self._points.get(session_id, 0)

    def close(self) -> None:
        self.closed = True


NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
OLD_SESSION = ChatSession("old-session", datetime(2025, 9, 18, tzinfo=timezone.utc))


def build_worker(
    *,
    dry_run: bool,
    sessions: FakeSessionRepository,
    vectors: FakeVectorRepository,
) -> ChatbotSessionsWorker:
    return ChatbotSessionsWorker(
        Settings(dry_run=dry_run),
        session_repository=sessions,
        vector_repository=vectors,
        clock=lambda: NOW,
    )


def test_worker_removes_qdrant_points_before_mongo_session() -> None:
    events: list[str] = []
    sessions = FakeSessionRepository([OLD_SESSION], events=events)
    vectors = FakeVectorRepository({"old-session": 2}, events=events)

    build_worker(dry_run=False, sessions=sessions, vectors=vectors).run()

    assert events == [
        "mongo:list",
        "mongo:revalidate:old-session",
        "qdrant:delete:old-session",
        "mongo:delete:old-session",
    ]
    assert sessions.closed is True
    assert vectors.closed is True


def test_worker_dry_run_only_counts_points(caplog: pytest.LogCaptureFixture) -> None:
    events: list[str] = []
    sessions = FakeSessionRepository([OLD_SESSION], events=events)
    vectors = FakeVectorRepository({"old-session": 3}, events=events)
    caplog.set_level(logging.INFO)

    build_worker(dry_run=True, sessions=sessions, vectors=vectors).run()

    assert "qdrant:count:old-session" in events
    assert "qdrant:delete:old-session" not in events
    assert "mongo:delete:old-session" not in events
    assert "pontos_qdrant=3" in caplog.text


def test_worker_preserves_session_when_qdrant_fails() -> None:
    events: list[str] = []
    sessions = FakeSessionRepository([OLD_SESSION], events=events)
    vectors = FakeVectorRepository(
        {"old-session": 1},
        failing_sessions={"old-session"},
        events=events,
    )

    with pytest.raises(ChatbotSessionCleanupError, match="1 erro"):
        build_worker(dry_run=False, sessions=sessions, vectors=vectors).run()

    assert "mongo:delete:old-session" not in events


def test_worker_preserves_session_that_is_no_longer_expired() -> None:
    events: list[str] = []
    sessions = FakeSessionRepository([OLD_SESSION], revalidated=set(), events=events)
    vectors = FakeVectorRepository({"old-session": 1}, events=events)

    build_worker(dry_run=False, sessions=sessions, vectors=vectors).run()

    assert "qdrant:delete:old-session" not in events
    assert "mongo:delete:old-session" not in events


def test_worker_reports_mongo_delete_mismatch() -> None:
    sessions = FakeSessionRepository(
        [OLD_SESSION],
        delete_results={"old-session": False},
    )
    vectors = FakeVectorRepository({"old-session": 1})

    with pytest.raises(ChatbotSessionCleanupError, match="1 erro"):
        build_worker(dry_run=False, sessions=sessions, vectors=vectors).run()


def test_one_calendar_year_before_handles_leap_day() -> None:
    leap_day = datetime(2024, 2, 29, 8, 30, tzinfo=timezone.utc)

    assert one_calendar_year_before(leap_day) == datetime(
        2023, 2, 28, 8, 30, tzinfo=timezone.utc
    )


def test_worker_is_registered() -> None:
    from src.workers import worker_registry

    assert "chatbot-sessions" in worker_registry.names()
