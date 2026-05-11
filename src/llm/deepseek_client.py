from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float


class DeepSeekClient:
    def __init__(self, model_config: Dict[str, Any]):
        self.provider = model_config.get("provider", "deepseek")
        self.base_url = model_config.get("base_url", "https://api.deepseek.com")
        self.model = model_config.get("model", "deepseek-v4-flash")
        self.temperature = float(model_config.get("temperature", 0.3))
        self.max_tokens = int(model_config.get("max_tokens", 2000))
        self.timeout_seconds = float(model_config.get("timeout_seconds", 60))
        self.max_retries = int(model_config.get("max_retries", 2))
        self.retry_backoff_seconds = float(model_config.get("retry_backoff_seconds", 1.0))
        self.min_request_interval_seconds = float(model_config.get("min_request_interval_seconds", 0.0))
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self._client = None
        self._rate_limit_lock = threading.Lock()
        self._last_request_at = 0.0

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        client = self._ensure_client()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }

        started_at = time.perf_counter()
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                self._respect_rate_limit()
                completion = client.chat.completions.create(**payload)
                latency_seconds = time.perf_counter() - started_at
                content = completion.choices[0].message.content or ""
                usage = self._extract_usage(completion)
                return LLMResponse(
                    content=content.strip(),
                    model=self.model,
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    total_tokens=usage["total_tokens"],
                    latency_seconds=latency_seconds,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))

        raise RuntimeError(
            f"DeepSeek API call failed after {self.max_retries + 1} attempt(s): {last_error}"
        )

    def _ensure_client(self) -> Any:
        if not self.api_key:
            raise RuntimeError("Environment variable DEEPSEEK_API_KEY is not set.")
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "Missing dependency: openai. Run `pip install -r requirements.txt`."
                ) from exc
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self._client

    def _respect_rate_limit(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        with self._rate_limit_lock:
            now = time.perf_counter()
            elapsed = now - self._last_request_at
            wait_seconds = self.min_request_interval_seconds - elapsed
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_at = time.perf_counter()

    @staticmethod
    def _extract_usage(completion: Any) -> Dict[str, int]:
        usage = getattr(completion, "usage", None)
        prompt_tokens = DeepSeekClient._read_usage_value(usage, "prompt_tokens")
        completion_tokens = DeepSeekClient._read_usage_value(usage, "completion_tokens")
        total_tokens = DeepSeekClient._read_usage_value(usage, "total_tokens")
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _read_usage_value(usage: Any, key: str) -> int:
        if usage is None:
            return 0
        if isinstance(usage, dict):
            return int(usage.get(key) or 0)
        return int(getattr(usage, key, 0) or 0)
