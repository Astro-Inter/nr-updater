import json
import logging
import os
import re
import traceback
from datetime import datetime, timezone

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

SERVICE_NAME = "nr-updater"
JOB_NAME = "atualizar-nrs"

_SENSITIVE_ENVIRONMENT_VARIABLES = (
    "OTEL_EXPORTER_OTLP_HEADERS",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MONGO_URI",
    "POSTGRES_PASSWORD",
)
_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)(authorization\s*[:=]\s*(?:basic|bearer)(?:%20|\s)+)[^\s,;]+"
    ),
    re.compile(
        r"(?i)((?:password|token|api[_-]?key|secret)\s*[:=]\s*)[^\s,;]+"
    ),
)


def _deployment_environment() -> str:
    return "production" if os.getenv("GITHUB_ACTIONS") == "true" else "development"


def _resource_attributes() -> dict[str, str]:
    attributes = {
        "service.name": SERVICE_NAME,
        "deployment.environment.name": _deployment_environment(),
        "job.name": os.getenv("GITHUB_JOB", JOB_NAME),
        "worker.name": "github-actions"
        if os.getenv("GITHUB_ACTIONS") == "true"
        else "local",
    }
    service_version = os.getenv("GITHUB_SHA")
    if service_version:
        attributes["service.version"] = service_version[:40]
    return attributes


class SensitiveDataFilter(logging.Filter):
    """Remove secrets conhecidos antes de qualquer handler emitir o registro."""

    def __init__(self) -> None:
        super().__init__()
        self._secret_values = tuple(
            value
            for name in _SENSITIVE_ENVIRONMENT_VARIABLES
            if (value := os.getenv(name)) and len(value) >= 4
        )

    def _redact(self, value: object) -> str:
        text = str(value)
        for secret in self._secret_values:
            text = text.replace(secret, "[REDACTED]")
        for pattern in _SENSITIVE_PATTERNS:
            text = pattern.sub(r"\1[REDACTED]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.getMessage())
        record.args = ()

        if record.exc_info:
            exception_type, exception, _ = record.exc_info
            stacktrace = self._redact("".join(traceback.format_exception(*record.exc_info)))
            record.__dict__["exception.type"] = exception_type.__name__
            record.__dict__["exception.message"] = self._redact(exception)
            record.__dict__["exception.stacktrace"] = stacktrace
            record.exc_text = stacktrace
            record.exc_info = None
        return True


class ExcludeOpenTelemetryInternalLogs(logging.Filter):
    """Evita realimentar no exporter os erros gerados pelo próprio exporter."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry.")


class JsonFormatter(logging.Formatter):
    """Formata o stdout como JSON, mantendo os mesmos campos do sinal OTLP."""

    def __init__(self, resource_attributes: dict[str, str]) -> None:
        super().__init__()
        self._resource_attributes = resource_attributes

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service.name": self._resource_attributes["service.name"],
            "environment": self._resource_attributes[
                "deployment.environment.name"
            ],
            "job": self._resource_attributes["job.name"],
            "worker": self._resource_attributes["worker.name"],
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attribute in ("operation", "duration_ms", "status"):
            if hasattr(record, attribute):
                payload[attribute] = getattr(record, attribute)
        if record.exc_text:
            payload["error"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False, default=str)


class Observability:
    def __init__(
        self,
        logger_provider: LoggerProvider | None = None,
        otlp_handler: LoggingHandler | None = None,
    ) -> None:
        self.enabled = logger_provider is not None
        self._logger_provider = logger_provider
        self._otlp_handler = otlp_handler
        self._closed = False

    def shutdown(self) -> None:
        """Envia o lote pendente antes de encerrar o processo curto do cron."""
        if self._logger_provider is None or self._closed:
            return
        self._closed = True
        if self._otlp_handler is not None:
            logging.getLogger().removeHandler(self._otlp_handler)
        try:
            self._logger_provider.force_flush(timeout_millis=10_000)
            self._logger_provider.shutdown()
        except Exception:
            logging.getLogger(__name__).exception(
                "Falha ao finalizar a exportação OTLP.",
                extra={"operation": "shutdown_observability", "status": "error"},
            )
        finally:
            if self._otlp_handler is not None:
                self._otlp_handler.close()


def configure_observability() -> Observability:
    """Configura stdout sempre e OTLP apenas quando endpoint e headers existem."""
    resource_attributes = _resource_attributes()
    sensitive_data_filter = SensitiveDataFilter()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JsonFormatter(resource_attributes))
    console_handler.addFilter(sensitive_data_filter)
    root_logger.addHandler(console_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    if not endpoint and not headers:
        return Observability()
    if not endpoint or not headers:
        logging.getLogger(__name__).warning(
            "Exportação OTLP desabilitada: configure endpoint e headers em conjunto.",
            extra={"operation": "configure_observability", "status": "disabled"},
        )
        return Observability()

    try:
        logger_provider = LoggerProvider(
            resource=Resource.create(resource_attributes), shutdown_on_exit=False
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter())
        )
        otlp_handler = LoggingHandler(
            level=logging.NOTSET, logger_provider=logger_provider
        )
        otlp_handler.addFilter(ExcludeOpenTelemetryInternalLogs())
        otlp_handler.addFilter(sensitive_data_filter)
        root_logger.addHandler(otlp_handler)
    except Exception:
        logging.getLogger(__name__).exception(
            "Não foi possível inicializar a exportação OTLP; usando somente stdout.",
            extra={"operation": "configure_observability", "status": "error"},
        )
        return Observability()

    logging.getLogger(__name__).info(
        "Exportação de logs via OTLP habilitada.",
        extra={"operation": "configure_observability", "status": "enabled"},
    )
    return Observability(logger_provider, otlp_handler)
