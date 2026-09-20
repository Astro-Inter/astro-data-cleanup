"""Acesso às sessões de conversa armazenadas no MongoDB."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class MongoSessionDataError(ValueError):
    """Indica um documento de sessão incompatível com o contrato esperado."""


@dataclass(frozen=True, slots=True)
class ChatSession:
    """Identificação e data necessárias para expurgar uma sessão."""

    session_id: str
    started_at: datetime


class ChatSessionRepository(Protocol):
    """Contrato das operações de sessão usadas pelo worker."""

    def list_expired(self, cutoff: datetime) -> Iterable[ChatSession]: ...

    def is_expired(self, session_id: str, cutoff: datetime) -> bool: ...

    def delete_expired(self, session: ChatSession, cutoff: datetime) -> bool: ...

    def close(self) -> None: ...


class MongoCollectionProtocol(Protocol):
    """Parte da API de coleção usada neste módulo."""

    def find(
        self,
        query: Mapping[str, object],
        projection: Mapping[str, int],
    ) -> Iterable[Mapping[str, object]]: ...

    def find_one(
        self,
        query: Mapping[str, object],
        projection: Mapping[str, int],
    ) -> Mapping[str, object] | None: ...

    def delete_one(self, query: Mapping[str, object]) -> object: ...


class MongoClientProtocol(Protocol):
    """Parte do MongoClient necessária para encerrar a conexão."""

    def close(self) -> None: ...


class MongoChatSessionRepository:
    """Consulta e remove documentos da coleção ``sessoes``."""

    def __init__(
        self,
        mongodb_uri: str,
        database_name: str,
        collection_name: str = "sessoes",
        *,
        client: MongoClientProtocol | None = None,
        collection: MongoCollectionProtocol | None = None,
    ) -> None:
        if client is None or collection is None:
            try:
                from pymongo import MongoClient
            except ImportError as error:
                raise RuntimeError(
                    "Dependência pymongo não instalada. Execute a instalação do projeto."
                ) from error

            mongo_client = MongoClient(mongodb_uri, tz_aware=True)
            client = mongo_client
            collection = mongo_client[database_name][collection_name]

        self._client = client
        self._collection = collection

    def list_expired(self, cutoff: datetime) -> Iterable[ChatSession]:
        """Lista sessões iniciadas antes da data limite."""
        query = self._expiration_filter(cutoff)
        projection = {"_id": 1, "iniciada_em": 1}
        for document in self._collection.find(query, projection):
            yield self._to_session(document)

    def is_expired(self, session_id: str, cutoff: datetime) -> bool:
        """Revalida a sessão imediatamente antes do expurgo."""
        query = {"_id": session_id, **self._expiration_filter(cutoff)}
        return self._collection.find_one(query, {"_id": 1}) is not None

    def delete_expired(self, session: ChatSession, cutoff: datetime) -> bool:
        """Remove uma sessão somente se a data original ainda for elegível."""
        query = {
            "_id": session.session_id,
            "iniciada_em": {
                "$eq": session.started_at,
                "$type": "date",
                "$lt": cutoff,
            },
        }
        result = self._collection.delete_one(query)
        return int(getattr(result, "deleted_count", 0)) == 1

    def close(self) -> None:
        """Encerra o cliente MongoDB."""
        self._client.close()

    @staticmethod
    def _expiration_filter(cutoff: datetime) -> dict[str, object]:
        return {"iniciada_em": {"$type": "date", "$lt": cutoff}}

    @staticmethod
    def _to_session(document: Mapping[str, object]) -> ChatSession:
        session_id = document.get("_id")
        started_at = document.get("iniciada_em")

        if not isinstance(session_id, str) or not session_id:
            raise MongoSessionDataError("A sessão deve possuir um _id textual não vazio.")
        if not isinstance(started_at, datetime):
            raise MongoSessionDataError(
                f"A sessão {session_id} deve possuir iniciada_em como BSON Date."
            )
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        return ChatSession(session_id=session_id, started_at=started_at)
