# llm_client.py
import os
import json
import requests
import logging
import random
import time
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(
        self,
        text_gen_api_url: str,
        text_gen_api_key: str,
        text_gen_model: str,
        critic_api_url: str,
        critic_api_key: str,
        critic_model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        request_delay: float = 0.0,
        api_max_retries: int = 4,
        api_retry_base_delay: float = 1.0,
        api_retry_max_delay: float = 30.0,
        api_retry_jitter: float = 0.25,
        api_rate_limit_cooldown: float = 15.0,
    ):
        self.text_gen_config = {
            "url": text_gen_api_url,
            "key": text_gen_api_key,
            "model": text_gen_model
        }
        self.critic_config = {
            "url": critic_api_url,
            "key": critic_api_key,
            "model": critic_model
        }
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self.request_delay = request_delay
        self.api_max_retries = max(1, api_max_retries)
        self.api_retry_base_delay = max(0.0, api_retry_base_delay)
        self.api_retry_max_delay = max(self.api_retry_base_delay, api_retry_max_delay)
        self.api_retry_jitter = max(0.0, api_retry_jitter)
        self.api_rate_limit_cooldown = max(0.0, api_rate_limit_cooldown)
        self._next_request_at = 0.0
        self.retry_metrics = {"api_retries": 0, "retry_reasons": {}, "rate_limit_cooldowns": []}

    def call_text_gen(self, prompt: str, system_prompt: str = "",
                      temperature: Optional[float] = None,
                      max_tokens: Optional[int] = None) -> str:
        """Gọi API cho Text Generator với tham số tùy chọn"""
        return self._call_api(
            self.text_gen_config,
            prompt,
            system_prompt,
            temperature or self.default_temperature,
            max_tokens or self.default_max_tokens
        )

    def call_critic(self, prompt: str, system_prompt: str = "",
                    temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None) -> str:
        """Gọi API cho Critic Agent với tham số tùy chọn"""
        return self._call_api(
            self.critic_config,
            prompt,
            system_prompt,
            temperature or self.default_temperature,
            max_tokens or self.default_max_tokens
        )

    def _call_api(self, config: Dict, prompt: str, system_prompt: str,
                  temperature: float, max_tokens: int) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['key']}"
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": config["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        for attempt in range(self.api_max_retries):
            try:
                self._wait_for_request_slot()
                response = requests.post(
                    config["url"], headers=headers, json=payload, timeout=300
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"].get("content") or ""
            except (KeyError, IndexError) as error:
                raise Exception(f"Invalid API response format: {error}") from error
            except requests.exceptions.RequestException as error:
                if not self.is_retryable_error(error) or attempt + 1 >= self.api_max_retries:
                    raise Exception(f"API call failed: {error}") from error
                reason = self.retry_reason(error)
                delay = self._retry_delay(error, attempt)
                self.retry_metrics["api_retries"] += 1
                self.retry_metrics["retry_reasons"][reason] = self.retry_metrics["retry_reasons"].get(reason, 0) + 1
                if reason == "http_429":
                    self.retry_metrics["rate_limit_cooldowns"].append(delay)
                logger.warning("Retrying API after %s (attempt %s/%s, cooldown %.2fs)", reason, attempt + 1, self.api_max_retries, delay)
                time.sleep(delay)

    @staticmethod
    def is_retryable_error(error: Exception) -> bool:
        if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        if isinstance(error, requests.exceptions.HTTPError) and error.response is not None:
            return error.response.status_code == 429 or 500 <= error.response.status_code < 600
        return False

    @staticmethod
    def retry_reason(error: Exception) -> str:
        if isinstance(error, requests.exceptions.Timeout):
            return "timeout"
        if isinstance(error, requests.exceptions.ConnectionError):
            return "network"
        if isinstance(error, requests.exceptions.HTTPError) and error.response is not None:
            return f"http_{error.response.status_code}"
        return "transient"

    def compute_backoff(self, attempt: int) -> float:
        capped = min(self.api_retry_max_delay, self.api_retry_base_delay * (2 ** attempt))
        return capped + random.uniform(0.0, self.api_retry_jitter)

    def _wait_for_request_slot(self) -> None:
        """Serialize API calls so text generation and critic share one request budget."""
        now = time.monotonic()
        if self._next_request_at > now:
            time.sleep(self._next_request_at - now)
        self._next_request_at = time.monotonic() + self.request_delay

    def _retry_delay(self, error: Exception, attempt: int) -> float:
        delay = self.compute_backoff(attempt)
        if self.retry_reason(error) != "http_429":
            return delay
        retry_after = self.retry_after_seconds(error)
        return max(delay, retry_after or 0.0, self.api_rate_limit_cooldown)

    @staticmethod
    def retry_after_seconds(error: Exception) -> Optional[float]:
        if not isinstance(error, requests.exceptions.HTTPError) or error.response is None:
            return None
        value = error.response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None
