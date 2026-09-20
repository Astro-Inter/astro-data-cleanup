"""Configurações globais lidas de variáveis de ambiente."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


class SettingsError(ValueError):
    """Indica uma variável de ambiente ausente ou inválida."""


def parse_bool(value: str, variable_name: str) -> bool:
    """Converte uma variável textual para booleano de forma estrita."""
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise SettingsError(
        f"{variable_name} deve ser true/false, 1/0, yes/no ou on/off; recebido: {value!r}"
    )


@dataclass(frozen=True, slots=True)
class Settings:
    """Configurações compartilhadas por todos os workers."""

    app_env: str = "development"
    dry_run: bool = True
    log_level: str = "INFO"
    postgres_url: str | None = None
    firebase_project_id: str | None = None
    firebase_credentials_base64: str | None = None
    mongodb_uri: str | None = None
    mongodb_database: str | None = None
    mongodb_sessions_collection: str = "sessoes"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_summaries_collection: str = "memoria_resumos"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Cria as configurações a partir do ambiente informado."""
        source = os.environ if environ is None else environ
        app_env = source.get("APP_ENV", "development").strip() or "development"
        dry_run = parse_bool(source.get("DRY_RUN", "true"), "DRY_RUN")
        log_level = source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        postgres_url = source.get("POSTGRES_URL", "").strip() or None
        firebase_project_id = source.get("FIREBASE_PROJECT_ID", "").strip() or None
        firebase_credentials_base64 = (
            source.get("FIREBASE_CREDENTIALS_BASE64", "").strip() or None
        )
        mongodb_uri = source.get("MONGODB_URI", "").strip() or None
        mongodb_database = source.get("MONGODB_DATABASE", "").strip() or None
        mongodb_sessions_collection = (
            source.get("MONGODB_SESSIONS_COLLECTION", "sessoes").strip() or "sessoes"
        )
        qdrant_url = source.get("QDRANT_URL", "").strip() or None
        qdrant_api_key = source.get("QDRANT_API_KEY", "").strip() or None
        qdrant_summaries_collection = (
            source.get("QDRANT_SUMMARIES_COLLECTION", "memoria_resumos").strip()
            or "memoria_resumos"
        )

        if log_level not in VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(VALID_LOG_LEVELS))
            raise SettingsError(f"LOG_LEVEL deve ser um de: {allowed}")

        return cls(
            app_env=app_env,
            dry_run=dry_run,
            log_level=log_level,
            postgres_url=postgres_url,
            firebase_project_id=firebase_project_id,
            firebase_credentials_base64=firebase_credentials_base64,
            mongodb_uri=mongodb_uri,
            mongodb_database=mongodb_database,
            mongodb_sessions_collection=mongodb_sessions_collection,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            qdrant_summaries_collection=qdrant_summaries_collection,
        )

    @staticmethod
    def require(value: str | None, variable_name: str) -> str:
        """Exige uma configuração apenas quando o worker que a usa for executado."""
        if value is None:
            raise SettingsError(f"Variável obrigatória não configurada: {variable_name}")
        return value
