import json
import unittest
from unittest.mock import patch
import httpx
from infrastructure.openrouter import analyze_nr, OpenRouterError

DATA = {"descricao": "Seguranca da atividade.", "objetivo": "Prevenir acidentes.",
        "aplicabilidade": "Trabalhadores abrangidos.", "tempo_reciclagem_meses": 12, "usabilidade": "Colaborador"}

def reply(content=None, finish="stop", **message):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {
        "content": json.dumps(DATA) if content is None else content, **message}}]})

class OpenRouterTest(unittest.TestCase):
    def run_with(self, outcomes):
        client = patch("httpx.Client"); factory = client.start(); self.addCleanup(client.stop)
        post = factory.return_value.__enter__.return_value.post
        post.side_effect = outcomes
        return post

    def test_http_errors_are_bounded_and_never_expose_body_or_key(self):
        for status in (400, 401, 402, 403, 404, 429, 500, 503):
            with self.subTest(status=status), patch("httpx.Client") as factory, patch("time.sleep"):
                post = factory.return_value.__enter__.return_value.post
                post.return_value = httpx.Response(status, json={"error": {"message": "private-key body"}})
                with self.assertRaises(OpenRouterError) as error:
                    analyze_nr("Texto fonte", "Prompt", "private-key")
                self.assertNotIn("private-key", str(error.exception))
                self.assertNotIn("body", str(error.exception))
                self.assertEqual(post.call_count, 2 if status in (429, 500, 503) else 1)

    def test_long_retry_after_does_not_retry_or_sleep(self):
        post = self.run_with([httpx.Response(429, headers={"retry-after": "30"})])
        with patch("time.sleep") as sleep, self.assertRaises(OpenRouterError):
            analyze_nr("Texto", "Prompt", "test-key")
        self.assertEqual(post.call_count, 1); sleep.assert_not_called()

    def test_truncation_retries_with_larger_budget(self):
        post = self.run_with([reply("", "length"), reply()])
        self.assertEqual(analyze_nr("Texto", "Prompt", "test-key").usabilidade, "Colaborador")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 8192)

    def test_invalid_output_never_returns_an_analysis(self):
        for response in [reply(""), reply("not-json"), reply("{}"), reply(finish="tool_calls", tool_calls=[{}]),
                         reply(finish="length"), httpx.Response(200, json={"error": {"code": 402}})]:
            with self.subTest(response=response.status_code), patch("httpx.Client") as factory:
                factory.return_value.__enter__.return_value.post.return_value = response
                with self.assertRaises(OpenRouterError): analyze_nr("Texto", "Prompt", "test-key")

    def test_timeouts_retry_once_and_preserve_text(self):
        post = self.run_with([httpx.ReadTimeout("private-key"), reply()])
        with patch("time.sleep"):
            self.assertEqual(analyze_nr("Texto original", "Prompt", "test-key").usabilidade, "Colaborador")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["messages"][1]["content"], "Texto original")

    def test_missing_key_empty_and_oversize_text_never_call_provider(self):
        with patch("httpx.Client") as client:
            for text, key in [("Texto", ""), ("", "key"), ("a" * 120001, "key")]:
                with self.assertRaises(OpenRouterError): analyze_nr(text, "Prompt", key)
            client.assert_not_called()
