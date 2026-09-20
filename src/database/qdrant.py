"""Acesso aos vetores de resumos de sessões armazenados no Qdrant."""

from __future__ import annotations

from typing import Protocol


class QdrantDeleteError(RuntimeError):
    """Indica que o Qdrant não confirmou a conclusão da exclusão."""


class SessionVectorRepository(Protocol):
    """Contrato das operações Qdrant usadas pelo worker."""

    def count_by_session_id(self, session_id: str) -> int: ...

    def delete_by_session_id(self, session_id: str) -> int: ...

    def close(self) -> None: ...


class QdrantSessionVectorRepository:
    """Gerencia pontos vinculados pelo payload ``session_id``."""

    def __init__(
        self,
        qdrant_url: str,
        api_key: str,
        collection_name: str = "memoria_resumos",
        *,
        client: object | None = None,
    ) -> None:
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as error:
            raise RuntimeError(
                "Dependência qdrant-client não instalada. Execute a instalação do projeto."
            ) from error

        self._client = client or QdrantClient(
            url=qdrant_url,
            api_key=api_key,
            timeout=60,
        )
        self._models = models
        self._collection_name = collection_name

    def count_by_session_id(self, session_id: str) -> int:
        """Conta exatamente os pontos associados à sessão."""
        result = self._client.count(
            collection_name=self._collection_name,
            count_filter=self._session_filter(session_id),
            exact=True,
        )
        return int(result.count)

    def delete_by_session_id(self, session_id: str) -> int:
        """Remove todos os pontos da sessão e aguarda a conclusão no Qdrant."""
        points_count = self.count_by_session_id(session_id)
        selector = self._models.FilterSelector(filter=self._session_filter(session_id))
        result = self._client.delete(
            collection_name=self._collection_name,
            points_selector=selector,
            wait=True,
        )
        status = getattr(result, "status", None)
        status_value = getattr(status, "value", status)
        if status_value != "completed":
            raise QdrantDeleteError(
                f"O Qdrant não confirmou a exclusão da sessão {session_id}."
            )
        return points_count

    def close(self) -> None:
        """Encerra os transportes HTTP/gRPC do cliente Qdrant."""
        self._client.close()

    def _session_filter(self, session_id: str) -> object:
        return self._models.Filter(
            must=[
                self._models.FieldCondition(
                    key="session_id",
                    match=self._models.MatchValue(value=session_id),
                )
            ]
        )
