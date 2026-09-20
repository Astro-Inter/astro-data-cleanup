"""Ponto central de execução dos workers."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from src.config.logging_config import configure_logging
from src.config.settings import Settings, SettingsError
from src.workers import worker_registry
from src.workers.registry import UnknownWorkerError

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Cria o parser da linha de comando."""
    parser = argparse.ArgumentParser(
        prog="astro-data-cleanup",
        description="Executa workers de manutenção e expurgo de dados.",
    )
    parser.add_argument(
        "worker",
        nargs="?",
        help="Nome do worker ou 'all' para executar todos os workers registrados.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_workers",
        help="Lista os workers registrados e encerra.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Executa a CLI e devolve um código compatível com processos de automação."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except SettingsError as error:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.error("Configuração inválida: %s", error)
        return 2

    configure_logging(settings.log_level)

    if args.list_workers:
        names = worker_registry.names()
        if names:
            for name in names:
                print(name)
        else:
            print("Nenhum worker registrado.")
        return 0

    if args.worker is None:
        parser.print_help()
        return 0

    try:
        worker_registry.execute(args.worker, settings)
    except UnknownWorkerError as error:
        LOGGER.error("%s", error)
        return 2
    except SettingsError as error:
        LOGGER.error("Configuração inválida: %s", error)
        return 2
    except Exception:
        LOGGER.exception("Execução encerrada devido a um erro no worker.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
