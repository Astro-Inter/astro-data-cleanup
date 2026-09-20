"""Integrações externas compartilhadas pelos workers."""

from src.integrations.firebase import FirebaseAuthGateway, FirebaseUser

__all__ = ["FirebaseAuthGateway", "FirebaseUser"]
