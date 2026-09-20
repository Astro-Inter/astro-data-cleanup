"""Expurgo de mensagens de conversa antigas no MongoDB."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from src.config.settings import Settings
from src.database.mongodb import (
    ConversationMessage,
    ConversationRepository,
    MongoConversationRepository,
)
from src.workers.base import BaseWorker
from src.workers.retention import calendar_years_before


class OldConversationsCleanupError(RuntimeError):
    """Indica que uma ou mais mensagens não puderam ser expurgadas."""


@dataclass(slots=True)
class CleanupSummary:
    """Contadores registrados ao final da execução."""

    messages_found: int = 0
    messages_removed: int = 0
    errors: int = 0


class OldConversationsWorker(BaseWorker):
    """Remove mensagens com mais de dois anos da coleção configurada."""

    name = "old-conversations"

    def __init__(
        self,
        settings: Settings,
        *,
        repository: ConversationRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(settings)
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self) -> None:
        """Expurga mensagens elegíveis, respeitando o modo DRY RUN."""
        summary = CleanupSummary()
        repository: ConversationRepository | None = None

        try:
            repository = self._repository or self._build_repository()
            cutoff = calendar_years_before(self._clock(), 2)
            self.logger.info("Data limite: %s", cutoff.isoformat())
            self._process_messages(repository, cutoff, summary)
        except Exception:
            summary.errors += 1
            raise
        finally:
            summary.errors += self._close_repository(repository)
            self._log_summary(summary)

        if summary.errors:
            raise OldConversationsCleanupError(
                f"O worker terminou com {summary.errors} erro(s) de expurgo."
            )

    def _process_messages(
        self,
        repository: ConversationRepository,
        cutoff: datetime,
        summary: CleanupSummary,
    ) -> None:
        expired_messages = tuple(repository.list_expired(cutoff))
        summary.messages_found = len(expired_messages)

        for message in expired_messages:
            try:
                self._process_message(repository, message, cutoff, summary)
            except Exception:
                summary.errors += 1
                self.logger.exception(
                    "Erro ao processar mensagem: message_id=%s",
                    message.message_id,
                )

    def _process_message(
        self,
        repository: ConversationRepository,
        message: ConversationMessage,
        cutoff: datetime,
        summary: CleanupSummary,
    ) -> None:
        if not repository.is_expired(message.message_id, cutoff):
            self.logger.warning(
                "Mensagem preservada após revalidação: message_id=%s",
                message.message_id,
            )
            return

        if self.settings.dry_run:
            self.logger.info(
                "DRY RUN: mensagem seria removida: message_id=%s data=%s",
                message.message_id,
                message.sent_at.isoformat(),
            )
            return

        if not repository.delete_expired(message, cutoff):
            summary.errors += 1
            self.logger.error(
                "A mensagem não foi excluída após a revalidação: message_id=%s",
                message.message_id,
            )
            return

        summary.messages_removed += 1
        self.logger.info("Mensagem expurgada: message_id=%s", message.message_id)

    def _build_repository(self) -> ConversationRepository:
        mongodb_uri = Settings.require(self.settings.mongodb_uri, "MONGODB_URI")
        database = Settings.require(self.settings.mongodb_database, "MONGODB_DATABASE")
        return MongoConversationRepository(
            mongodb_uri,
            database,
            self.settings.mongodb_messages_collection,
        )

    def _close_repository(self, repository: ConversationRepository | None) -> int:
        if repository is None:
            return 0
        try:
            repository.close()
        except Exception:
            self.logger.exception("Erro ao encerrar o cliente de MongoDB.")
            return 1
        return 0

    def _log_summary(self, summary: CleanupSummary) -> None:
        self.logger.info("Mensagens encontradas: %d", summary.messages_found)
        self.logger.info("Mensagens removidas: %d", summary.messages_removed)
        self.logger.info("Erros encontrados: %d", summary.errors)
