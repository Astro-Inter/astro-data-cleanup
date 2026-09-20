"""Configuração central de logs locais e exportação opcional via OTLP."""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import traceback
from copy import copy
from datetime import UTC, datetime
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

SERVICE_NAME = "astro-data-cleanup"
_OTEL_PROVIDER: LoggerProvider | None = None
_SENSITIVE_ENV_SUFFIXES = (
    "_API_KEY",
    "_CREDENTIALS_BASE64",
    "_HEADERS",
    "_PASSWORD",
    "_SECRET",
    "_TOKEN",
    "_URI",
    "_URL",
)
_URI_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)
_NAMED_SECRET = re.compile(
    r"(?i)(authorization|api[_-]?key|password|secret|token)\s*([=:]\s*)([^,;\s]+)"
)


@lru_cache(maxsize=1)
def _service_version() -> str:
    try:
        return version(SERVICE_NAME)
    except PackageNotFoundError:
        return "unknown"


class SensitiveDataRedactor:
    """Remove credenciais conhecidas sem registrar seus valores."""

    def __init__(self) -> None:
        self._values = tuple(
            value
            for name, value in os.environ.items()
            if value and name.upper().endswith(_SENSITIVE_ENV_SUFFIXES)
        )

    def redact(self, value: str) -> str:
        redacted = value
        for sensitive_value in self._values:
            redacted = redacted.replace(sensitive_value, "[REDACTED]")
        redacted = _URI_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", redacted)
        return _NAMED_SECRET.sub(r"\1\2[REDACTED]", redacted)


class JsonFormatter(logging.Formatter):
    """Emite JSON de uma linha, adequado ao console do GitHub Actions."""

    def __init__(self, *, environment: str, job_name: str | None, redactor: SensitiveDataRedactor):
        super().__init__()
        self._environment = environment
        self._job_name = job_name
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service.name": SERVICE_NAME,
            "service.version": _service_version(),
            "deployment.environment.name": self._environment,
            "message": self._redactor.redact(record.getMessage()),
        }
        if self._job_name:
            payload["job.name"] = self._job_name

        for attribute in ("worker.name", "operation", "duration", "status"):
            attribute_value = getattr(record, attribute, None)
            if attribute_value is not None:
                payload[attribute] = attribute_value

        if record.exc_info:
            exception_type = record.exc_info[0]
            payload["error"] = {
                "type": exception_type.__name__ if exception_type else "Exception",
                "stack_trace": self._redactor.redact(
                    "".join(traceback.format_exception(*record.exc_info))
                ),
            }

        return json.dumps(payload, ensure_ascii=False, default=str)


class SafeOTLPLoggingHandler(LoggingHandler):
    """Sanitiza corpo e stack trace antes de entregar o registro ao exporter."""

    def __init__(self, *, logger_provider: LoggerProvider, redactor: SensitiveDataRedactor):
        super().__init__(level=logging.NOTSET, logger_provider=logger_provider)
        self._redactor = redactor

    def emit(self, record: logging.LogRecord) -> None:
        safe_record = copy(record)
        safe_record.msg = self._redactor.redact(record.getMessage())
        safe_record.args = ()

        if record.exc_info:
            exception_type, exception, _ = record.exc_info
            safe_record.__dict__["exception.type"] = (
                exception_type.__name__ if exception_type else "Exception"
            )
            safe_record.__dict__["exception.message"] = self._redactor.redact(str(exception))
            safe_record.__dict__["exception.stacktrace"] = self._redactor.redact(
                "".join(traceback.format_exception(*record.exc_info))
            )
            safe_record.exc_info = None
            safe_record.exc_text = None

        super().emit(safe_record)


def shutdown_logging() -> None:
    """Drena os logs pendentes do processo curto e encerra o provider OTLP."""
    global _OTEL_PROVIDER
    if _OTEL_PROVIDER is not None:
        _OTEL_PROVIDER.shutdown()
        _OTEL_PROVIDER = None


def configure_logging(
    level: str = "INFO",
    *,
    environment: str = "development",
    job_name: str | None = None,
) -> bool:
    """Configura console JSON e, quando possível, exportação OTLP.

    A exportação só é habilitada quando endpoint e headers estão presentes. O
    retorno informa se o handler OTLP foi configurado.
    """
    global _OTEL_PROVIDER
    shutdown_logging()

    redactor = SensitiveDataRedactor()
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        JsonFormatter(environment=environment, job_name=job_name, redactor=redactor)
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    if not endpoint or not headers:
        return False

    try:
        attributes: dict[str, str] = {
            "service.name": SERVICE_NAME,
            "service.version": _service_version(),
            "deployment.environment.name": environment,
        }
        if job_name:
            attributes["job.name"] = job_name

        provider = LoggerProvider(resource=Resource(attributes), shutdown_on_exit=False)
        provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        root_logger.addHandler(SafeOTLPLoggingHandler(logger_provider=provider, redactor=redactor))
        _OTEL_PROVIDER = provider
    except Exception:
        root_logger.warning(
            "Exportação OTLP não pôde ser inicializada; mantendo somente logs no console.",
            exc_info=True,
        )
        return False

    return True


atexit.register(shutdown_logging)
