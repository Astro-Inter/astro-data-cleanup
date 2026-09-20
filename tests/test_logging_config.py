import json
import logging

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

from src.config import logging_config


@pytest.fixture(autouse=True)
def restore_root_logger() -> None:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    yield

    logging_config.shutdown_logging()
    root_logger.handlers = original_handlers
    root_logger.setLevel(original_level)


def test_logging_uses_json_console_without_otel_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    enabled = logging_config.configure_logging(
        "INFO", environment="test", job_name="example-worker"
    )
    logging.getLogger("test").info(
        "Execução concluída",
        extra={"worker.name": "example-worker", "status": "success", "duration": 1.25},
    )

    payload = json.loads(capsys.readouterr().err)
    assert enabled is False
    assert payload["level"] == "INFO"
    assert payload["service.name"] == "astro-data-cleanup"
    assert payload["deployment.environment.name"] == "test"
    assert payload["job.name"] == "example-worker"
    assert payload["worker.name"] == "example-worker"
    assert payload["status"] == "success"
    assert payload["duration"] == 1.25
    assert payload["message"] == "Execução concluída"


def test_logging_requires_endpoint_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.example.test")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    assert logging_config.configure_logging() is False


def test_logging_enables_otel_when_both_variables_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemoryLogRecordExporter()
    monkeypatch.setattr(logging_config, "OTLPLogExporter", lambda: exporter)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic fake")

    enabled = logging_config.configure_logging(environment="production", job_name="cleanup")
    logging.getLogger("test").warning(
        "Evento exportado", extra={"worker.name": "example-worker"}
    )

    assert enabled is True
    assert logging_config._OTEL_PROVIDER is not None
    assert logging_config._OTEL_PROVIDER.force_flush() is True
    exported = exporter.get_finished_logs()
    assert len(exported) == 1
    assert exported[0].log_record.body == "Evento exportado"
    assert exported[0].log_record.attributes["worker.name"] == "example-worker"
    resource = exported[0].resource.attributes
    assert resource["service.name"] == "astro-data-cleanup"
    assert resource["deployment.environment.name"] == "production"
    assert resource["job.name"] == "cleanup"
    assert "service.instance.id" not in resource


def test_logging_redacts_known_secrets_and_preserves_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_uri = "postgresql://user:password@example.test/database"
    exporter = InMemoryLogRecordExporter()
    monkeypatch.setattr(logging_config, "OTLPLogExporter", lambda: exporter)
    monkeypatch.setenv("POSTGRES_URL", secret_uri)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic fake")
    logging_config.configure_logging()

    try:
        raise RuntimeError(f"Falha ao conectar em {secret_uri}")
    except RuntimeError:
        logging.getLogger("test").exception("Erro de conexão: %s", secret_uri)

    rendered = capsys.readouterr().err
    payload = json.loads(rendered)
    assert secret_uri not in rendered
    assert "[REDACTED]" in rendered
    assert payload["error"]["type"] == "RuntimeError"
    assert "Traceback" in payload["error"]["stack_trace"]
    assert logging_config._OTEL_PROVIDER is not None
    assert logging_config._OTEL_PROVIDER.force_flush() is True
    exported = exporter.get_finished_logs()
    assert len(exported) == 1
    assert secret_uri not in str(exported[0].log_record.body)
    assert secret_uri not in str(exported[0].log_record.attributes)
    assert "exception.stacktrace" in exported[0].log_record.attributes
