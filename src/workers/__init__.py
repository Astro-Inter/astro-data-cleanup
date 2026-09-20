"""Workers disponíveis e seu registro central."""

from src.workers.registry import WorkerRegistry

worker_registry = WorkerRegistry()

__all__ = ["worker_registry"]
