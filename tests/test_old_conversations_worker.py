from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

import pytest

from src.config.settings import Settings
from src.database.mongodb import ConversationMessage
from src.workers.old_conversations.worker import (
    OldConversationsCleanupError,
    OldConversationsWorker,
)
from src.workers.retention import calendar_years_before


class FakeConversationRepository:
    def __init__(
        self,
        messages: Iterable[ConversationMessage],
        *,
        revalidated: set[str] | None = None,
        delete_results: dict[str, bool] | None = None,
        failing_messages: set[str] | None = None,
    ) -> None:
        self._messages = tuple(messages)
        self._revalidated = (
            revalidated
            if revalidated is not None
            else {message.message_id for message in self._messages}
        )
        self._delete_results = delete_results or {}
        self._failing_messages = failing_messages or set()
        self.events: list[str] = []
        self.cutoff: datetime | None = None
        self.closed = False

    def list_expired(self, cutoff: datetime) -> Iterable[ConversationMessage]:
        self.events.append("mongo:list")
        self.cutoff = cutoff
        return iter(self._messages)

    def is_expired(self, message_id: str, cutoff: datetime) -> bool:
        self.events.append(f"mongo:revalidate:{message_id}")
        if message_id in self._failing_messages:
            raise RuntimeError("mongo unavailable")
        return message_id in self._revalidated

    def delete_expired(self, message: ConversationMessage, cutoff: datetime) -> bool:
        self.events.append(f"mongo:delete:{message.message_id}")
        if message.message_id in self._failing_messages:
            raise RuntimeError("mongo unavailable")
        return self._delete_results.get(message.message_id, True)

    def close(self) -> None:
        self.closed = True


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
OLD_MESSAGE = ConversationMessage(
    "old-message",
    datetime(2024, 9, 19, 12, tzinfo=timezone.utc),
)


def build_worker(
    *,
    dry_run: bool,
    repository: FakeConversationRepository,
) -> OldConversationsWorker:
    return OldConversationsWorker(
        Settings(dry_run=dry_run),
        repository=repository,
        clock=lambda: NOW,
    )


def test_worker_deletes_message_older_than_two_years() -> None:
    repository = FakeConversationRepository([OLD_MESSAGE])

    build_worker(dry_run=False, repository=repository).run()

    assert repository.cutoff == datetime(2024, 9, 20, 12, tzinfo=timezone.utc)
    assert repository.events == [
        "mongo:list",
        "mongo:revalidate:old-message",
        "mongo:delete:old-message",
    ]
    assert repository.closed is True


def test_worker_dry_run_does_not_delete_message(caplog: pytest.LogCaptureFixture) -> None:
    repository = FakeConversationRepository([OLD_MESSAGE])
    caplog.set_level(logging.INFO)

    build_worker(dry_run=True, repository=repository).run()

    assert "mongo:delete:old-message" not in repository.events
    assert "DRY RUN: mensagem seria removida" in caplog.text


def test_worker_preserves_message_that_is_no_longer_expired() -> None:
    repository = FakeConversationRepository([OLD_MESSAGE], revalidated=set())

    build_worker(dry_run=False, repository=repository).run()

    assert "mongo:delete:old-message" not in repository.events


@pytest.mark.parametrize("failure_mode", ["mismatch", "exception"])
def test_worker_reports_individual_delete_failure(failure_mode: str) -> None:
    repository = FakeConversationRepository(
        [OLD_MESSAGE],
        delete_results={"old-message": failure_mode != "mismatch"},
        failing_messages={"old-message"} if failure_mode == "exception" else set(),
    )

    with pytest.raises(OldConversationsCleanupError, match="1 erro"):
        build_worker(dry_run=False, repository=repository).run()

    assert repository.closed is True


def test_worker_continues_after_an_individual_failure() -> None:
    second_message = ConversationMessage(
        "second-message",
        datetime(2023, 1, 1, tzinfo=timezone.utc),
    )
    repository = FakeConversationRepository(
        [OLD_MESSAGE, second_message],
        failing_messages={"old-message"},
    )

    with pytest.raises(OldConversationsCleanupError, match="1 erro"):
        build_worker(dry_run=False, repository=repository).run()

    assert "mongo:delete:second-message" in repository.events


def test_calendar_years_before_handles_leap_day() -> None:
    leap_day = datetime(2024, 2, 29, 8, 30, tzinfo=timezone.utc)

    assert calendar_years_before(leap_day, 2) == datetime(
        2022, 2, 28, 8, 30, tzinfo=timezone.utc
    )


def test_worker_is_registered() -> None:
    from src.workers import worker_registry

    assert "old-conversations" in worker_registry.names()
