"""Registro e roteamento dos workers disponíveis."""

from __future__ import annotations

import logging

from src.config.settings import Settings
from src.workers.base import BaseWorker

LOGGER = logging.getLogger(__name__)


class UnknownWorkerError(LookupError):
    """Indica a solicitação de um worker não registrado."""


class WorkerRegistry:
    """Mantém classes de workers e executa uma ou todas por nome."""

    def __init__(self) -> None:
        self._workers: dict[str, type[BaseWorker]] = {}

    def register(self, worker_class: type[BaseWorker]) -> type[BaseWorker]:
        """Registra uma classe e também pode ser usado como decorator."""
        name = getattr(worker_class, "name", "").strip()
        if not name:
            raise ValueError("Todo worker deve declarar um nome não vazio.")
        if name == "all":
            raise ValueError("'all' é reservado para executar todos os workers.")
        if name in self._workers:
            raise ValueError(f"Worker já registrado: {name}")

        self._workers[name] = worker_class
        return worker_class

    def names(self) -> tuple[str, ...]:
        """Lista os nomes registrados em ordem estável."""
        return tuple(sorted(self._workers))

    def create(self, name: str, settings: Settings) -> BaseWorker:
        """Instancia um worker registrado."""
        try:
            worker_class = self._workers[name]
        except KeyError as error:
            available = ", ".join(self.names()) or "nenhum"
            raise UnknownWorkerError(
                f"Worker desconhecido: {name}. Workers disponíveis: {available}."
            ) from error
        return worker_class(settings)

    def execute(self, name: str, settings: Settings) -> None:
        """Executa um worker pelo nome ou todos quando o nome for ``all``."""
        if name != "all":
            self.create(name, settings).execute()
            return

        names = self.names()
        if not names:
            LOGGER.warning("Nenhum worker registrado para execução.")
            return

        for worker_name in names:
            self.create(worker_name, settings).execute()
