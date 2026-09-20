"""Acesso ao PostgreSQL para validação de contas do Firebase."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

LIST_FIREBASE_UIDS_QUERY = """
    SELECT firebase_uid
    FROM conta
    WHERE firebase_uid IS NOT NULL
"""

FIREBASE_UID_EXISTS_QUERY = """
    SELECT EXISTS (
        SELECT 1
        FROM conta
        WHERE firebase_uid = %s
    )
"""


class AccountRepository(Protocol):
    """Contrato mínimo usado pelo worker de usuários órfãos."""

    def list_firebase_uids(self) -> set[str]: ...

    def firebase_uid_exists(self, firebase_uid: str) -> bool: ...

    def close(self) -> None: ...


class CursorProtocol(Protocol):
    """Parte do cursor DB-API necessária neste módulo."""

    def __enter__(self) -> CursorProtocol: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def execute(self, query: str, params: tuple[str, ...] | None = None) -> object: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class ConnectionProtocol(Protocol):
    """Parte da conexão DB-API necessária neste módulo."""

    def cursor(self) -> CursorProtocol: ...

    def close(self) -> None: ...


class PostgresAccountRepository:
    """Consulta UIDs em ``conta`` incluindo suas tabelas filhas no PostgreSQL."""

    def __init__(
        self,
        postgres_url: str,
        *,
        connection: ConnectionProtocol | None = None,
    ) -> None:
        if connection is None:
            try:
                import psycopg
            except ImportError as error:
                raise RuntimeError(
                    "Dependência psycopg não instalada. Execute a instalação do projeto."
                ) from error
            connection = psycopg.connect(postgres_url, autocommit=True)

        self._connection = connection

    def list_firebase_uids(self) -> set[str]:
        """Carrega todos os UIDs existentes em ``conta`` e tabelas herdadas."""
        with self._connection.cursor() as cursor:
            cursor.execute(LIST_FIREBASE_UIDS_QUERY)
            rows = cursor.fetchall()
        return {str(row[0]) for row in rows if row and row[0] is not None}

    def firebase_uid_exists(self, firebase_uid: str) -> bool:
        """Revalida um UID imediatamente antes de uma possível exclusão."""
        with self._connection.cursor() as cursor:
            cursor.execute(FIREBASE_UID_EXISTS_QUERY, (firebase_uid,))
            row = cursor.fetchone()
        return bool(row and row[0])

    def close(self) -> None:
        """Encerra a conexão com o PostgreSQL."""
        self._connection.close()
