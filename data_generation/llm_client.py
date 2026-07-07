# llm_client.py
import os
import json
import requests
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

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
        request_delay: float = 0.0
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
        import time
        if self.request_delay > 0:
            time.sleep(self.request_delay)
            
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

        try:
            response = requests.post(
                config["url"],
                headers=headers,
                json=payload,
                timeout=300  # Tăng lên 300 giây
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"].get("content") or ""
        except requests.exceptions.RequestException as e:
            raise Exception(f"API call failed: {e}")
        except (KeyError, IndexError) as e:
            raise Exception(f"Invalid API response format: {e}")