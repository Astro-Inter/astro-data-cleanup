import base64
import json

import pytest

from src.integrations.firebase import FirebaseConfigurationError, decode_firebase_credentials


def encode_credentials(data: object) -> str:
    serialized = json.dumps(data).encode("utf-8")
    return base64.b64encode(serialized).decode("ascii")


def test_decode_firebase_credentials_accepts_matching_project() -> None:
    encoded = encode_credentials({"project_id": "astro-test", "private_key": "secret"})

    result = decode_firebase_credentials(encoded, "astro-test")

    assert result["project_id"] == "astro-test"


def test_decode_firebase_credentials_rejects_invalid_base64() -> None:
    with pytest.raises(FirebaseConfigurationError, match="Base64"):
        decode_firebase_credentials("invalid%%%", "astro-test")


def test_decode_firebase_credentials_rejects_another_project() -> None:
    encoded = encode_credentials({"project_id": "wrong-project"})

    with pytest.raises(FirebaseConfigurationError, match="não corresponde"):
        decode_firebase_credentials(encoded, "astro-test")
