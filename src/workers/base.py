"""Contrato comum para todos os workers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from time import perf_counter

from src.config.settings import Settings


class BaseWorker(ABC):
    """Fornece ciclo de vida, logging e configurações comuns aos workers."""

    name: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.name}")

    def execute(self) -> None:
        """Executa o worker com logs padronizados de início, erro e duração."""
        started_at = perf_counter()
        self.logger.info("Worker iniciado: %s", self.name)
        dry_run_status = "habilitado" if self.settings.dry_run else "desabilitado"
        self.logger.info("Modo DRY RUN: %s", dry_run_status)

        try:
            self.run()
        except Exception:
            self.logger.exception("Worker falhou: %s", self.name)
            raise
        finally:
            duration = perf_counter() - started_at
            self.logger.info("Worker finalizado: %s (%.2f segundos)", self.name, duration)

    @abstractmethod
    def run(self) -> None:
        """Executa a regra específica do worker."""
