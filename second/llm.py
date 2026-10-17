"""Clients for open-weight models: local Ollama, Ollama Cloud, or Gemma on Google AI Studio."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


@dataclass
class CallStats:
    calls: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0


def parse_json_object(text: str) -> dict:
    """Pull the first JSON object out of a model reply, tolerating code fences."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("the model did not return a JSON object")
    candidate = cleaned[start : end + 1]
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            data = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise LLMError("the model returned invalid JSON")


class OllamaClient:
    """Ollama's /api/chat, either on this machine or on ollama.com."""

    def __init__(self, url: str, model: str, api_key: str | None = None, timeout: float = 300.0):
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.local = "ollama.com" not in self.url
        self.structured = self.local  # Ollama's cloud doesn't support schema-constrained output
        self.send_think = True
        self.stats = CallStats()
        self.label = f"{model} via Ollama on this computer" if self.local else f"{model} via Ollama Cloud"

    def chat_json(self, system: str, user: str, schema: dict, temperature: float = 0.4) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": 4096},
        }
        if self.structured:
            payload["format"] = schema
        if self.send_think:
            payload["think"] = False
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        start = time.perf_counter()
        try:
            response = httpx.post(f"{self.url}/api/chat", json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMError(f"couldn't reach Ollama at {self.url} ({exc.__class__.__name__})") from exc
        if response.status_code == 400 and self.send_think and "think" in response.text.lower():
            self.send_think = False
            return self.chat_json(system, user, schema, temperature)
        if response.status_code >= 400:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text[:200]}")
        body = response.json()
        self.stats.calls += 1
        self.stats.seconds += time.perf_counter() - start
        self.stats.prompt_tokens += body.get("prompt_eval_count") or 0
        self.stats.output_tokens += body.get("eval_count") or 0
        return parse_json_object(body.get("message", {}).get("content", ""))

    def check(self) -> str:
        if not self.local:
            return f"using {self.model} on Ollama Cloud"
        try:
            tags = httpx.get(f"{self.url}/api/tags", timeout=5.0).json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama is not running at {self.url}. Start the Ollama app first.") from exc
        names = {m.get("name") for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise LLMError(f"Model {self.model} is not downloaded. Run: ollama pull {self.model}")
        return f"{self.model} is ready in Ollama"


class GeminiClient:
    """Gemma served by the Gemini API (Google AI Studio)."""

    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: float = 120.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.send_thinking_config = True
        self.stats = CallStats()
        self.label = f"{model} via Google AI Studio"

    def chat_json(self, system: str, user: str, schema: dict, temperature: float = 0.4) -> dict:
        config: dict = {"temperature": temperature}
        if self.send_thinking_config:
            config["thinkingConfig"] = {"thinkingLevel": "minimal"}
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        start = time.perf_counter()
        try:
            response = httpx.post(
                self.endpoint.format(model=self.model),
                json=payload,
                headers={"x-goog-api-key": self.api_key},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"couldn't reach the Gemini API ({exc.__class__.__name__})") from exc
        if response.status_code == 400 and self.send_thinking_config and "think" in response.text.lower():
            self.send_thinking_config = False
            return self.chat_json(system, user, schema, temperature)
        if response.status_code == 429:
            raise LLMError("the free Gemma quota is used up for now; try again in a minute")
        if response.status_code >= 400:
            raise LLMError(f"Gemini API returned {response.status_code}: {response.text[:200]}")
        body = response.json()
        self.stats.calls += 1
        self.stats.seconds += time.perf_counter() - start
        usage = body.get("usageMetadata", {})
        self.stats.prompt_tokens += usage.get("promptTokenCount") or 0
        self.stats.output_tokens += usage.get("candidatesTokenCount") or 0
        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise LLMError("the Gemini API returned no text") from exc
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        return parse_json_object(text)

    def check(self) -> str:
        return f"using {self.model} on Google AI Studio"


class NoModelClient:
    """Used when no model is configured: every note falls back to the verified templates."""

    label = "no language model (template notes)"

    def __init__(self) -> None:
        self.stats = CallStats()

    def chat_json(self, system: str, user: str, schema: dict, temperature: float = 0.4) -> dict:
        raise LLMError("no language model configured")

    def check(self) -> str:
        return "no language model configured; notes will use templates"


def make_client(settings: Settings):
    backend = settings.llm_backend
    if backend == "ollama":
        return OllamaClient(settings.ollama_url, settings.ollama_model, settings.ollama_api_key)
    if backend == "gemini":
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    if backend in {"none", "off", "template"}:
        return NoModelClient()
    raise LLMError(f"unknown SECOND_LLM_BACKEND: {backend}")
