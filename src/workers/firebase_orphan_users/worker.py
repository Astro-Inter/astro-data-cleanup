"""Expurgo de contas do Firebase sem correspondência no PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import Settings
from src.database.postgres import AccountRepository, PostgresAccountRepository
from src.integrations.firebase import FirebaseAdminAuthClient, FirebaseAuthGateway, FirebaseUser
from src.workers.base import BaseWorker


class FirebaseOrphanCleanupError(RuntimeError):
    """Indica que uma ou mais contas não puderam ser removidas."""


@dataclass(slots=True)
class CleanupSummary:
    """Contadores registrados ao final da execução."""

    analyzed: int = 0
    orphans: int = 0
    removed: int = 0
    errors: int = 0


class FirebaseOrphanUsersWorker(BaseWorker):
    """Remove do Firebase contas sem ``firebase_uid`` correspondente em ``conta``."""

    name = "firebase-orphan-users"

    def __init__(
        self,
        settings: Settings,
        *,
        firebase_client: FirebaseAuthGateway | None = None,
        account_repository: AccountRepository | None = None,
    ) -> None:
        super().__init__(settings)
        self._firebase_client = firebase_client
        self._account_repository = account_repository

    def run(self) -> None:
        """Identifica, revalida e remove contas órfãs, respeitando o DRY RUN."""
        summary = CleanupSummary()
        firebase_client: FirebaseAuthGateway | None = None
        account_repository: AccountRepository | None = None

        try:
            firebase_client = self._firebase_client or self._build_firebase_client()
            account_repository = self._account_repository or self._build_account_repository()
            self._process_users(firebase_client, account_repository, summary)
        except Exception:
            summary.errors += 1
            raise
        finally:
            summary.errors += self._close_resources(firebase_client, account_repository)
            self._log_summary(summary)

        if summary.errors:
            raise FirebaseOrphanCleanupError(
                f"O worker terminou com {summary.errors} erro(s) de exclusão."
            )

    def _process_users(
        self,
        firebase_client: FirebaseAuthGateway,
        account_repository: AccountRepository,
        summary: CleanupSummary,
    ) -> None:
        database_uids = account_repository.list_firebase_uids()
        firebase_users = tuple(firebase_client.list_users())
        summary.analyzed = len(firebase_users)

        candidates = [user for user in firebase_users if user.uid not in database_uids]
        for user in candidates:
            if account_repository.firebase_uid_exists(user.uid):
                self.logger.warning(
                    "Candidato preservado após revalidação no PostgreSQL: uid=%s",
                    user.uid,
                )
                continue

            summary.orphans += 1
            if self.settings.dry_run:
                self.logger.info(
                    "DRY RUN: usuário seria removido do Firebase: %s",
                    self._user_label(user),
                )
                continue

            try:
                firebase_client.delete_user(user.uid)
            except Exception:
                summary.errors += 1
                self.logger.exception(
                    "Erro ao remover usuário do Firebase: %s",
                    self._user_label(user),
                )
            else:
                summary.removed += 1
                self.logger.info(
                    "Usuário removido do Firebase: %s",
                    self._user_label(user),
                )

    def _build_firebase_client(self) -> FirebaseAuthGateway:
        project_id = Settings.require(self.settings.firebase_project_id, "FIREBASE_PROJECT_ID")
        credentials = Settings.require(
            self.settings.firebase_credentials_base64,
            "FIREBASE_CREDENTIALS_BASE64",
        )
        return FirebaseAdminAuthClient(project_id, credentials)

    def _build_account_repository(self) -> AccountRepository:
        postgres_url = Settings.require(self.settings.postgres_url, "POSTGRES_URL")
        return PostgresAccountRepository(postgres_url)

    def _close_resources(
        self,
        firebase_client: FirebaseAuthGateway | None,
        account_repository: AccountRepository | None,
    ) -> int:
        errors = 0
        for resource_name, resource in (
            ("PostgreSQL", account_repository),
            ("Firebase", firebase_client),
        ):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                errors += 1
                self.logger.exception("Erro ao encerrar o cliente de %s.", resource_name)
        return errors

    def _log_summary(self, summary: CleanupSummary) -> None:
        self.logger.info("Usuários analisados: %d", summary.analyzed)
        self.logger.info("Usuários órfãos encontrados: %d", summary.orphans)
        self.logger.info("Usuários removidos: %d", summary.removed)
        self.logger.info("Erros encontrados: %d", summary.errors)

    @staticmethod
    def _user_label(user: FirebaseUser) -> str:
        email = user.email or "sem-email"
        return f"uid={user.uid} email={email}"
