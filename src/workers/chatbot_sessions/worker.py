"""Expurgo de sessões antigas no MongoDB e de seus pontos no Qdrant."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from src.config.settings import Settings
from src.database.mongodb import ChatSession, ChatSessionRepository, MongoChatSessionRepository
from src.database.qdrant import QdrantSessionVectorRepository, SessionVectorRepository
from src.workers.base import BaseWorker


class ChatbotSessionCleanupError(RuntimeError):
    """Indica que uma ou mais sessões não puderam ser expurgadas."""


@dataclass(slots=True)
class CleanupSummary:
    """Contadores registrados ao final da execução."""

    sessions_found: int = 0
    mongo_removed: int = 0
    qdrant_removed: int = 0
    errors: int = 0


def one_calendar_year_before(moment: datetime) -> datetime:
    """Calcula a retenção anual preservando horário e fuso UTC."""
    if moment.tzinfo is None:
        raise ValueError("O relógio do worker deve fornecer uma data com fuso horário.")

    normalized = moment.astimezone(timezone.utc)
    try:
        return normalized.replace(year=normalized.year - 1)
    except ValueError:
        return normalized.replace(year=normalized.year - 1, day=28)


class ChatbotSessionsWorker(BaseWorker):
    """Remove sessões com mais de um ano e seus resumos vetoriais."""

    name = "chatbot-sessions"

    def __init__(
        self,
        settings: Settings,
        *,
        session_repository: ChatSessionRepository | None = None,
        vector_repository: SessionVectorRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(settings)
        self._session_repository = session_repository
        self._vector_repository = vector_repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self) -> None:
        """Expurga sessões elegíveis com estratégia Qdrant-primeiro."""
        summary = CleanupSummary()
        session_repository: ChatSessionRepository | None = None
        vector_repository: SessionVectorRepository | None = None

        try:
            session_repository = self._session_repository or self._build_session_repository()
            vector_repository = self._vector_repository or self._build_vector_repository()
            cutoff = one_calendar_year_before(self._clock())
            self.logger.info("Data limite: %s", cutoff.isoformat())
            self._process_sessions(session_repository, vector_repository, cutoff, summary)
        except Exception:
            summary.errors += 1
            raise
        finally:
            summary.errors += self._close_resources(session_repository, vector_repository)
            self._log_summary(summary)

        if summary.errors:
            raise ChatbotSessionCleanupError(
                f"O worker terminou com {summary.errors} erro(s) de expurgo."
            )

    def _process_sessions(
        self,
        sessions: ChatSessionRepository,
        vectors: SessionVectorRepository,
        cutoff: datetime,
        summary: CleanupSummary,
    ) -> None:
        expired_sessions = tuple(sessions.list_expired(cutoff))
        summary.sessions_found = len(expired_sessions)

        for session in expired_sessions:
            if not sessions.is_expired(session.session_id, cutoff):
                self.logger.warning(
                    "Sessão preservada após revalidação no MongoDB: session_id=%s",
                    session.session_id,
                )
                continue

            if self.settings.dry_run:
                self._simulate_removal(session, vectors, summary)
                continue

            self._remove_session(session, sessions, vectors, cutoff, summary)

    def _simulate_removal(
        self,
        session: ChatSession,
        vectors: SessionVectorRepository,
        summary: CleanupSummary,
    ) -> None:
        try:
            points_count = vectors.count_by_session_id(session.session_id)
        except Exception:
            summary.errors += 1
            self.logger.exception(
                "Erro ao consultar pontos no Qdrant: session_id=%s",
                session.session_id,
            )
            return

        self.logger.info(
            "DRY RUN: sessão seria removida: session_id=%s pontos_qdrant=%d",
            session.session_id,
            points_count,
        )

    def _remove_session(
        self,
        session: ChatSession,
        sessions: ChatSessionRepository,
        vectors: SessionVectorRepository,
        cutoff: datetime,
        summary: CleanupSummary,
    ) -> None:
        try:
            points_removed = vectors.delete_by_session_id(session.session_id)
        except Exception:
            summary.errors += 1
            self.logger.exception(
                "Erro ao remover pontos no Qdrant; sessão preservada no MongoDB: session_id=%s",
                session.session_id,
            )
            return

        summary.qdrant_removed += points_removed

        try:
            mongo_removed = sessions.delete_expired(session, cutoff)
        except Exception:
            summary.errors += 1
            self.logger.exception(
                "Pontos removidos, mas houve erro ao remover a sessão do MongoDB: session_id=%s",
                session.session_id,
            )
            return

        if not mongo_removed:
            summary.errors += 1
            self.logger.error(
                "Pontos removidos, mas a sessão não foi excluída do MongoDB: session_id=%s",
                session.session_id,
            )
            return

        summary.mongo_removed += 1
        self.logger.info(
            "Sessão expurgada: session_id=%s pontos_qdrant=%d",
            session.session_id,
            points_removed,
        )

    def _build_session_repository(self) -> ChatSessionRepository:
        mongodb_uri = Settings.require(self.settings.mongodb_uri, "MONGODB_URI")
        database = Settings.require(self.settings.mongodb_database, "MONGODB_DATABASE")
        return MongoChatSessionRepository(
            mongodb_uri,
            database,
            self.settings.mongodb_sessions_collection,
        )

    def _build_vector_repository(self) -> SessionVectorRepository:
        qdrant_url = Settings.require(self.settings.qdrant_url, "QDRANT_URL")
        api_key = Settings.require(self.settings.qdrant_api_key, "QDRANT_API_KEY")
        return QdrantSessionVectorRepository(
            qdrant_url,
            api_key,
            self.settings.qdrant_summaries_collection,
        )

    def _close_resources(
        self,
        sessions: ChatSessionRepository | None,
        vectors: SessionVectorRepository | None,
    ) -> int:
        errors = 0
        for resource_name, resource in (("Qdrant", vectors), ("MongoDB", sessions)):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                errors += 1
                self.logger.exception("Erro ao encerrar o cliente de %s.", resource_name)
        return errors

    def _log_summary(self, summary: CleanupSummary) -> None:
        self.logger.info("Sessões encontradas: %d", summary.sessions_found)
        self.logger.info("Sessões removidas do MongoDB: %d", summary.mongo_removed)
        self.logger.info("Pontos removidos do Qdrant: %d", summary.qdrant_removed)
        self.logger.info("Erros encontrados: %d", summary.errors)
