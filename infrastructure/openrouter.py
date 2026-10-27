"""Única saída de inferência Python: Luna pelo OpenRouter, com schema local."""
import json
import logging
import math
import time

import httpx
from pydantic import ValidationError
from schemas.nr_schema import NrAnalise

MODEL = "openai/gpt-6-luna"
URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_CHARACTERS = 120_000
TRANSIENT = {408, 429, 500, 502, 503, 504, 524, 529}
logger = logging.getLogger(__name__)


class OpenRouterError(ValueError):
    pass


def analyze_nr(text: str, prompt: str, key: str | None) -> NrAnalise:
    if not key or not key.strip():
        raise OpenRouterError("openrouter_not_configured")
    if not isinstance(text, str) or not text.strip():
        raise OpenRouterError("empty_nr_text")
    # Nunca gerar um candidato a partir de uma norma cortada silenciosamente.
    if len(text) > MAX_CHARACTERS:
        raise OpenRouterError("nr_text_too_large")
    payload = {
        "model": MODEL, "reasoning": {"effort": "none"}, "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "provider": {"require_parameters": True, "data_collection": "deny"},
        "messages": [{"role": "system", "content": prompt + "\nCONTRATO JSON:\n" +
                      json.dumps(NrAnalise.model_json_schema(), ensure_ascii=False)},
                     {"role": "user", "content": text}],
    }
    for attempt in range(2):
        retry, delay, code = False, 1, "openrouter_invalid_response"
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.post(URL, headers={"Authorization": f"Bearer {key}"}, json=payload)
            status = response.status_code
            if not response.is_success:
                raw = response.headers.get("retry-after", "1")
                try:
                    number = float(raw)
                    delay = min(60, max(1, math.ceil(number))) if math.isfinite(number) else 1
                except (ValueError, TypeError):
                    delay = 1
                code = f"openrouter_http_{status}"
                retry = status in TRANSIENT and delay <= 2
            else:
                data = response.json()
                if data.get("error"):
                    status = data["error"].get("code")
                    code = f"openrouter_http_{status}" if type(status) is int else "openrouter_invalid_response"
                    retry = status in TRANSIENT
                else:
                    choice = data["choices"][0]
                    if len(data["choices"]) != 1 or choice.get("finish_reason") != "stop" or choice["message"].get("tool_calls"):
                        if choice.get("finish_reason") == "length":
                            payload["max_tokens"] = 8192
                        raise ValueError()
                    result = NrAnalise.model_validate_json(choice["message"]["content"])
                    if not all(v.strip() for v in (result.descricao, result.objetivo, result.aplicabilidade)):
                        raise ValueError()
                    usage = {k: v for k, v in (data.get("usage") or {}).items()
                             if k in {"prompt_tokens", "completion_tokens", "total_tokens", "cost"}
                             and type(v) in (float, int) and math.isfinite(v)}
                    logger.info("OpenRouter modelo=%s uso=%s", MODEL, usage)
                    return result
        except (httpx.TimeoutException, httpx.TransportError):
            retry, code = True, "openrouter_unavailable"
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, ValidationError):
            retry, code = True, "openrouter_invalid_response"
            payload["messages"][0]["content"] += "\nRetorne somente JSON valido com todos os campos do contrato."
        if attempt or not retry:
            raise OpenRouterError(code) from None
        if code != "openrouter_invalid_response":
            time.sleep(delay)
    raise OpenRouterError("openrouter_unavailable")
