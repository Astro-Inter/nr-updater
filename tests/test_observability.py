import io
import json
import logging
import os
import unittest
from unittest.mock import patch

from observability import (
    JsonFormatter,
    SensitiveDataFilter,
    _resource_attributes,
    configure_observability,
)


class ObservabilityTest(unittest.TestCase):
    def test_resource_has_stable_service_metadata(self):
        with patch.dict(os.environ, {}, clear=True):
            attributes = _resource_attributes()

        self.assertEqual(attributes["service.name"], "nr-updater")
        self.assertEqual(
            attributes["deployment.environment.name"], "development"
        )
        self.assertEqual(attributes["job.name"], "atualizar-nrs")
        self.assertEqual(attributes["worker.name"], "local")

    def test_console_log_is_structured_and_redacts_secret(self):
        stream = io.StringIO()
        logger = logging.getLogger("test-observability")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.INFO)

        with patch.dict(os.environ, {"GROQ_API_KEY": "secret-value"}, clear=True):
            attributes = _resource_attributes()
            handler = logging.StreamHandler(stream)
            handler.addFilter(SensitiveDataFilter())
            handler.setFormatter(JsonFormatter(attributes))
            logger.addHandler(handler)
            logger.info(
                "processamento finalizado com token=secret-value",
                extra={"operation": "test", "status": "success"},
            )

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["service.name"], "nr-updater")
        self.assertEqual(payload["operation"], "test")
        self.assertNotIn("secret-value", payload["message"])
        self.assertIn("[REDACTED]", payload["message"])

    def test_missing_otel_credentials_keeps_local_logging_enabled(self):
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()
        try:
            with patch.dict(os.environ, {}, clear=True), patch(
                "sys.stderr", io.StringIO()
            ):
                observability = configure_observability()
                logging.getLogger("test-local-only").info("log local")

            self.assertFalse(observability.enabled)
            self.assertEqual(len(root_logger.handlers), 1)
        finally:
            for handler in root_logger.handlers:
                handler.close()
            root_logger.handlers[:] = original_handlers


if __name__ == "__main__":
    unittest.main()
