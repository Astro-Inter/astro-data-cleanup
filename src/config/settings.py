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

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Cria as configurações a partir do ambiente informado."""
        source = os.environ if environ is None else environ
        app_env = source.get("APP_ENV", "development").strip() or "development"
        dry_run = parse_bool(source.get("DRY_RUN", "true"), "DRY_RUN")
        log_level = source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"

        if log_level not in VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(VALID_LOG_LEVELS))
            raise SettingsError(f"LOG_LEVEL deve ser um de: {allowed}")

        return cls(app_env=app_env, dry_run=dry_run, log_level=log_level)
