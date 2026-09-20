"""Workers disponíveis e seu registro central."""

from src.workers.chatbot_sessions.worker import ChatbotSessionsWorker
from src.workers.firebase_orphan_users.worker import FirebaseOrphanUsersWorker
from src.workers.registry import WorkerRegistry

worker_registry = WorkerRegistry()
worker_registry.register(ChatbotSessionsWorker)
worker_registry.register(FirebaseOrphanUsersWorker)

__all__ = ["worker_registry"]
