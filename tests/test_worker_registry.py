import pytest

from src.config.settings import Settings
from src.workers.base import BaseWorker
from src.workers.registry import UnknownWorkerError, WorkerRegistry


class ExampleWorker(BaseWorker):
    name = "example"
    executions = 0

    def run(self) -> None:
        type(self).executions += 1


def test_registry_creates_and_executes_registered_worker() -> None:
    registry = WorkerRegistry()
    registry.register(ExampleWorker)
    ExampleWorker.executions = 0

    registry.execute("example", Settings())

    assert ExampleWorker.executions == 1


def test_registry_executes_all_workers() -> None:
    registry = WorkerRegistry()
    registry.register(ExampleWorker)
    ExampleWorker.executions = 0

    registry.execute("all", Settings())

    assert ExampleWorker.executions == 1


def test_registry_rejects_unknown_worker() -> None:
    registry = WorkerRegistry()

    with pytest.raises(UnknownWorkerError, match="missing"):
        registry.execute("missing", Settings())


def test_registry_rejects_duplicate_name() -> None:
    registry = WorkerRegistry()
    registry.register(ExampleWorker)

    with pytest.raises(ValueError, match="já registrado"):
        registry.register(ExampleWorker)
