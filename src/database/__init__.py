"""Clientes de persistência compartilhados pelos workers."""

from src.database.postgres import AccountRepository, PostgresAccountRepository

__all__ = ["AccountRepository", "PostgresAccountRepository"]
