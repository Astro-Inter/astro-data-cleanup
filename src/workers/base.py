"""Contrato comum para todos os workers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from time import perf_counter

from src.config.settings import Settings


class WorkerLoggerAdapter(logging.LoggerAdapter):
    """Inclui contexto estável do worker e preserva atributos por chamada."""

    def process(self, msg: object, kwargs: dict) -> tuple[object, dict]:
        call_extra = kwargs.get("extra", {})
        kwargs["extra"] = {**self.extra, **call_extra}
        return msg, kwargs


class BaseWorker(ABC):
    """Fornece ciclo de vida, logging e configurações comuns aos workers."""

    name: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        logger = logging.getLogger(f"{self.__class__.__module__}.{self.name}")
        self.logger = WorkerLoggerAdapter(logger, {"worker.name": self.name})

    def execute(self) -> None:
        """Executa o worker com logs padronizados de início, erro e duração."""
        started_at = perf_counter()
        status = "success"
        self.logger.info("Worker iniciado: %s", self.name, extra={"status": "started"})
        dry_run_status = "habilitado" if self.settings.dry_run else "desabilitado"
        self.logger.info("Modo DRY RUN: %s", dry_run_status)

        try:
            self.run()
        except Exception:
            status = "error"
            self.logger.exception("Worker falhou: %s", self.name, extra={"status": status})
            raise
        finally:
            duration = perf_counter() - started_at
            self.logger.info(
                "Worker finalizado: %s (%.2f segundos)",
                self.name,
                duration,
                extra={"duration": duration, "status": status},
            )

    @abstractmethod
    def run(self) -> None:
        """Executa a regra específica do worker."""
