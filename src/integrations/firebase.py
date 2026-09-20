"""Integração com o Firebase Authentication via Firebase Admin SDK."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


class FirebaseConfigurationError(ValueError):
    """Indica credenciais inválidas ou direcionadas ao projeto errado."""


@dataclass(frozen=True, slots=True)
class FirebaseUser:
    """Dados mínimos de uma conta necessários para o expurgo."""

    uid: str
    email: str | None = None


class FirebaseAuthGateway(Protocol):
    """Contrato mínimo do Firebase Authentication usado pelo worker."""

    def list_users(self) -> Iterable[FirebaseUser]: ...

    def delete_user(self, uid: str) -> None: ...

    def close(self) -> None: ...


def decode_firebase_credentials(encoded: str, expected_project_id: str) -> dict[str, object]:
    """Decodifica e valida o JSON Base64 da conta de serviço."""
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        credentials_data = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FirebaseConfigurationError(
            "FIREBASE_CREDENTIALS_BASE64 deve conter um JSON válido codificado em Base64."
        ) from error

    if not isinstance(credentials_data, dict):
        raise FirebaseConfigurationError("As credenciais do Firebase devem ser um objeto JSON.")

    credential_project_id = credentials_data.get("project_id")
    if credential_project_id != expected_project_id:
        raise FirebaseConfigurationError(
            "FIREBASE_PROJECT_ID não corresponde ao project_id das credenciais."
        )

    return credentials_data


class FirebaseAdminAuthClient:
    """Cliente concreto do Firebase Authentication."""

    def __init__(self, project_id: str, credentials_base64: str) -> None:
        try:
            import firebase_admin
            from firebase_admin import auth, credentials
        except ImportError as error:
            raise RuntimeError(
                "Dependência firebase-admin não instalada. Execute a instalação do projeto."
            ) from error

        credentials_data = decode_firebase_credentials(credentials_base64, project_id)
        certificate = credentials.Certificate(credentials_data)
        app_name = f"astro-data-cleanup-{uuid4().hex}"

        self._firebase_admin = firebase_admin
        self._auth = auth
        self._app = firebase_admin.initialize_app(
            certificate,
            options={"projectId": project_id},
            name=app_name,
        )

    def list_users(self) -> Iterable[FirebaseUser]:
        """Percorre todas as contas, usando a paginação do Admin SDK."""
        records = self._auth.list_users(app=self._app).iterate_all()
        for record in records:
            yield FirebaseUser(uid=record.uid, email=record.email)

    def delete_user(self, uid: str) -> None:
        """Exclui uma conta individualmente no Firebase Authentication."""
        self._auth.delete_user(uid, app=self._app)

    def close(self) -> None:
        """Libera a instância nomeada do Firebase criada para a execução."""
        self._firebase_admin.delete_app(self._app)
