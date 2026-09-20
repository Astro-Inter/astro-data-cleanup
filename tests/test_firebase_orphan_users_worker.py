from __future__ import annotations

import logging
from collections.abc import Iterable

import pytest

from src.config.settings import Settings
from src.integrations.firebase import FirebaseUser
from src.workers.firebase_orphan_users.worker import (
    FirebaseOrphanCleanupError,
    FirebaseOrphanUsersWorker,
)


class FakeFirebaseClient:
    def __init__(self, users: Iterable[FirebaseUser], failing_uid: str | None = None) -> None:
        self._users = tuple(users)
        self._failing_uid = failing_uid
        self.deleted: list[str] = []
        self.closed = False

    def list_users(self) -> Iterable[FirebaseUser]:
        return iter(self._users)

    def delete_user(self, uid: str) -> None:
        if uid == self._failing_uid:
            raise RuntimeError("firebase unavailable")
        self.deleted.append(uid)

    def close(self) -> None:
        self.closed = True


class FakeAccountRepository:
    def __init__(self, initial_uids: set[str], revalidated_uids: set[str] | None = None) -> None:
        self._initial_uids = initial_uids
        self._revalidated_uids = revalidated_uids or set()
        self.revalidated: list[str] = []
        self.closed = False

    def list_firebase_uids(self) -> set[str]:
        return self._initial_uids

    def firebase_uid_exists(self, firebase_uid: str) -> bool:
        self.revalidated.append(firebase_uid)
        return firebase_uid in self._revalidated_uids

    def close(self) -> None:
        self.closed = True


def build_worker(
    *,
    dry_run: bool,
    firebase: FakeFirebaseClient,
    repository: FakeAccountRepository,
) -> FirebaseOrphanUsersWorker:
    return FirebaseOrphanUsersWorker(
        Settings(dry_run=dry_run),
        firebase_client=firebase,
        account_repository=repository,
    )


def test_worker_removes_only_confirmed_orphan() -> None:
    firebase = FakeFirebaseClient(
        [FirebaseUser("existing"), FirebaseUser("orphan", "orphan@example.com")]
    )
    repository = FakeAccountRepository({"existing"})

    build_worker(dry_run=False, firebase=firebase, repository=repository).run()

    assert firebase.deleted == ["orphan"]
    assert repository.revalidated == ["orphan"]
    assert firebase.closed is True
    assert repository.closed is True


def test_worker_dry_run_does_not_delete_confirmed_orphan(caplog: pytest.LogCaptureFixture) -> None:
    firebase = FakeFirebaseClient([FirebaseUser("orphan")])
    repository = FakeAccountRepository(set())
    caplog.set_level(logging.INFO)

    build_worker(dry_run=True, firebase=firebase, repository=repository).run()

    assert firebase.deleted == []
    assert "DRY RUN: usuário seria removido" in caplog.text
    assert "Usuários órfãos encontrados: 1" in caplog.text


def test_worker_preserves_candidate_found_during_revalidation() -> None:
    firebase = FakeFirebaseClient([FirebaseUser("new-user")])
    repository = FakeAccountRepository(set(), {"new-user"})

    build_worker(dry_run=False, firebase=firebase, repository=repository).run()

    assert firebase.deleted == []


def test_worker_reports_delete_errors_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    firebase = FakeFirebaseClient(
        [FirebaseUser("broken"), FirebaseUser("removable")],
        failing_uid="broken",
    )
    repository = FakeAccountRepository(set())
    caplog.set_level(logging.INFO)

    with pytest.raises(FirebaseOrphanCleanupError, match="1 erro"):
        build_worker(dry_run=False, firebase=firebase, repository=repository).run()

    assert firebase.deleted == ["removable"]
    assert "Erros encontrados: 1" in caplog.text


def test_worker_is_registered() -> None:
    from src.workers import worker_registry

    assert "firebase-orphan-users" in worker_registry.names()
