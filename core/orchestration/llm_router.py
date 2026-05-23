"""
LLM Router - Multi-Provider Round-Robin with Automatic Failover
Manages free LLM APIs across providers to avoid rate limits
"""
import os
import time
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import requests
import threading

from core.foundation.runtime_paths import runtime_path

logger = logging.getLogger("LLMRouter")


class ProviderStatus(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    DOWN = "down"
    NO_KEY = "no_key"


@dataclass
class Provider:
    name: str
    base_url: str
    api_key_env: str
    models: List[str]
    daily_limit: int
    requests_made: int = 0
    errors_count: int = 0
    status: ProviderStatus = ProviderStatus.ACTIVE
    last_error_time: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    priority: int = 1  # Lower = higher priority

    @property
    def api_key(self) -> Optional[str]:
        return os.environ.get(self.api_key_env)

    @property
    def has_key(self) -> bool:
        return self.api_key is not None and len(self.api_key) > 10

    @property
    def remaining_requests(self) -> int:
        return max(0, self.daily_limit - self.requests_made)


class LLMRouter:
    """
    Intelligent LLM Router with:
    - Round-robin distribution across providers
    - Automatic failover on errors/rate limits
    - Smart model selection per task type
    - Usage tracking and rate limit management
    - Exponential backoff for failed providers
    """

    def __init__(self):
        self.providers: Dict[str, Provider] = {}
        self.current_index = 0
        self.provider_order: List[str] = []
        self.lock = threading.Lock()
        self.usage_log: List[Dict] = []
        self.last_reset = datetime.now()

        self._init_providers()
        self._load_usage_stats()

    def _init_providers(self):
        """Initialize all free LLM providers"""
        provider_configs = [
            {
                "name": "groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key_env": "GROQ_API_KEY",
                "models": [
                    "llama3-70b-8192",
                    "llama3-8b-8192",
                    "mixtral-8x7b-32768",
                    "gemma2-9b-it"
                ],
                "daily_limit": 14400,
                "priority": 1
            },
            {
                "name": "together",
                "base_url": "https://api.together.xyz/v1",
                "api_key_env": "TOGETHER_API_KEY",
                "models": [
                    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                    "meta-llama/Llama-3-8B-Instruct",
                    "mistralai/Mixtral-8x7B-Instruct-v0.1"
                ],
                "daily_limit": 6000,
                "priority": 2
            },
            {
                "name": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "models": [
                    "meta-llama/llama-3-70b-instruct",
                    "mistralai/mixtral-8x7b",
                    "nousresearch/nous-hermes-2-mixtral-8x7b-dpo"
                ],
                "daily_limit": 2000,
                "priority": 3
            },
            {
                "name": "xai",
                "base_url": "https://api.x.ai/v1",
                "api_key_env": "XAI_API_KEY",
                "models": [
                    "grok-2-latest",
                    "grok-2-vision-latest"
                ],
                "daily_limit": 1200,
                "priority": 4
            },
            {
                "name": "gemini",
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "api_key_env": "GEMINI_API_KEY",
                "models": [
                    "gemini-2.0-flash",
                    "gemini-1.5-flash",
                    "gemini-1.5-flash-8b"
                ],
                "daily_limit": 1500,
                "priority": 2
            },
            {
                "name": "hyperbolic",
                "base_url": "https://api.hyperbolic.xyz/v1",
                "api_key_env": "HYPERBOLIC_API_KEY",
                "models": [
                    "meta-llama/Llama-3.3-70B-Instruct",
                    "meta-llama/Meta-Llama-3-8B-Instruct"
                ],
                "daily_limit": 1000,
                "priority": 5
            },
            {
                "name": "nvidia",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key_env": "NVIDIA_API_KEY",
                "models": [
                    "meta/llama-3.1-70b-instruct",
                    "meta/llama-3.1-8b-instruct"
                ],
                "daily_limit": 1000,
                "priority": 5
            },
            {
                "name": "cerebras",
                "base_url": "https://api.cerebras.ai/v1",
                "api_key_env": "CEREBRAS_API_KEY",
                "models": [
                    "llama3.1-70b",
                    "llama3.1-8b"
                ],
                "daily_limit": 1000,
                "priority": 3
            }
        ]

        for config in provider_configs:
            provider = Provider(**config)
            self.providers[provider.name] = provider
            if provider.has_key:
                provider.status = ProviderStatus.ACTIVE
            else:
                provider.status = ProviderStatus.NO_KEY

        self._update_provider_order()

    def _update_provider_order(self):
        """Update provider order based on priority and availability"""
        active = [
            (name, p) for name, p in self.providers.items()
            if p.status in (ProviderStatus.ACTIVE, ProviderStatus.RATE_LIMITED)
            and p.has_key and p.remaining_requests > 0
        ]
        active.sort(key=lambda x: (x[1].priority, -x[1].remaining_requests))
        self.provider_order = [name for name, _ in active]

    def _load_usage_stats(self):
        """Load usage statistics from file"""
        stats_file = runtime_path("usage_stats.json")
        if os.path.exists(stats_file):
            try:
                with open(stats_file, 'r') as f:
                    data = json.load(f)
                saved_date = datetime.fromisoformat(data.get('date', '2000-01-01'))
                if saved_date.date() == datetime.now().date():
                    for name, count in data.get('usage', {}).items():
                        if name in self.providers:
                            self.providers[name].requests_made = count
            except Exception as e:
                logger.warning(f"Could not load usage stats: {e}")

    def _save_usage_stats(self):
        """Save usage statistics to file"""
        stats_file = runtime_path("usage_stats.json")
        data = {
            'date': datetime.now().isoformat(),
            'usage': {name: p.requests_made for name, p in self.providers.items()}
        }
        try:
            with open(stats_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Could not save usage stats: {e}")

    def get_next_provider(self, task_type: str = "general",
                          require_vision: bool = False) -> Optional[Provider]:
        """Get next available provider using round-robin with priority"""
        with self.lock:
            self._reset_if_new_day()
            self._update_provider_order()

            if not self.provider_order:
                logger.error("No providers available! Add API keys to environment variables.")
                return None

            # Try each provider in order
            for _ in range(len(self.provider_order)):
                if self.current_index >= len(self.provider_order):
                    self.current_index = 0

                name = self.provider_order[self.current_index]
                provider = self.providers[name]
                self.current_index += 1

                # Check cooldown
                if provider.cooldown_until and datetime.now() < provider.cooldown_until:
                    continue

                # Check rate limit
                if provider.remaining_requests <= 0:
                    provider.status = ProviderStatus.RATE_LIMITED
                    continue

                # Reset rate limited if time has passed
                if provider.status == ProviderStatus.RATE_LIMITED:
                    if provider.last_error_time:
                        cooldown = min(60 * (2 ** provider.errors_count), 3600)
                        if datetime.now() - provider.last_error_time > timedelta(seconds=cooldown):
                            provider.status = ProviderStatus.ACTIVE
                        else:
                            continue

                return provider

            return None

    def _reset_if_new_day(self):
        """Reset counters if it's a new day"""
        if datetime.now().date() != self.last_reset.date():
            for provider in self.providers.values():
                provider.requests_made = 0
                provider.errors_count = 0
                if provider.has_key:
                    provider.status = ProviderStatus.ACTIVE
                provider.cooldown_until = None
            self.last_reset = datetime.now()
            logger.info("Daily counters reset")

    def send_message(self,
                     messages: List[Dict[str, str]],
                     task_type: str = "general",
                     require_vision: bool = False,
                     temperature: float = 0.7,
                     max_tokens: int = 4096,
                     retries: int = 3) -> Dict[str, Any]:
        """
        Send message to LLM with automatic failover

        Args:
            messages: List of message dicts with 'role' and 'content'
            task_type: Type of task for model selection
            require_vision: Whether vision capabilities needed
            temperature: Sampling temperature
            max_tokens: Max response tokens
            retries: Number of retry attempts

        Returns:
            Dict with 'success', 'content', 'provider', 'model', 'error'
        """
        last_error = None

        for attempt in range(retries):
            provider = self.get_next_provider(task_type, require_vision)
            if not provider:
                return {
                    "success": False,
                    "content": None,
                    "error": "No providers available. Add API keys to environment variables.",
                    "provider": None,
                    "model": None
                }

            # Select model based on task type
            model = self._select_model(provider, task_type, require_vision)

            try:
                result = self._call_provider(
                    provider=provider,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

                if result["success"]:
                    provider.requests_made += 1
                    provider.errors_count = max(0, provider.errors_count - 1)
                    self._save_usage_stats()
                    self._log_usage(provider.name, model, task_type, True)
                    return result

                else:
                    raise Exception(result.get("error", "Unknown error"))

            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                last_error = str(e)
                provider.errors_count += 1
                provider.last_error_time = datetime.now()

                self._handle_provider_error(provider, last_error, attempt)
                self._log_usage(provider.name, model, task_type, False, last_error)

        return {
            "success": False,
            "content": None,
            "error": f"All providers failed. Last error: {last_error}",
            "provider": None,
            "model": None
        }

    # ── Error classification + handling  (dict dispatch, no elif) ────────────

    def _classify_error(self, err: str) -> str:
        """Classify error string into a category via frozenset membership."""
        el = err.lower()
        _PATTERNS: Dict[str, frozenset] = {
            "rate_limit": frozenset(["rate limit", "429", "too many requests",
                                     "quota exceeded"]),
            "auth":       frozenset(["authentication", "401", "unauthorized",
                                     "invalid api key", "forbidden"]),
        }
        # frozenset O(1) membership check per category
        for kind, pats in _PATTERNS.items():
            if any(p in el for p in pats):
                return kind
        return "generic"

    def _handle_provider_error(self, provider: Provider,
                               error_str: str, attempt: int) -> None:
        """Apply status + cooldown + exponential backoff — zero elif chains."""
        kind = self._classify_error(error_str)

        # O(1) dict dispatch for status transitions
        _STATUS_MAP: Dict[str, ProviderStatus] = {
            "rate_limit": ProviderStatus.RATE_LIMITED,
            "auth":       ProviderStatus.NO_KEY,
            "generic":    ProviderStatus.DOWN,
        }
        # O(1) dict dispatch for cooldown durations (seconds)
        _COOLDOWN_MAP: Dict[str, int] = {
            "rate_limit": 60,
            "auth":       0,
            "generic":    30,  # was 300 - changed to 30 as per fix 4
        }
        _LOG_FN: Dict[str, Callable] = {
            "rate_limit": lambda: logger.warning(
                f"{provider.name} rate-limited — cooldown "
                f"{_COOLDOWN_MAP['rate_limit']}s"),
            "auth":    lambda: logger.error(
                f"{provider.name} API key invalid"),
            "generic": lambda: logger.warning(
                f"{provider.name} down -- cooldown 30s"),
        }

        provider.status = _STATUS_MAP[kind]
        cd = _COOLDOWN_MAP[kind]
        cd and setattr(provider, "cooldown_until",
                       datetime.now() + timedelta(seconds=cd))
        _LOG_FN[kind]()

        # Use non-blocking async-aware wait (simulated for sync)
        pass  # Backoff is handled by cooldown_until; remove blocking sleep.

    def _select_model(self, provider: Provider, task_type: str,
                      require_vision: bool) -> str:
        """Select best model for task type — O(1) dict dispatch, no elif."""
        models = provider.models.copy()

        # Vision shortcut: prefer any model with 'vision' in name
        vision_preferred = [m for m in models if "vision" in m.lower()]
        models = (vision_preferred or models) if require_vision else models

        # O(1) dict dispatch: task_type → filter keywords
        _PREFER_KWORDS: Dict[str, List[str]] = {
            "coding":  ["code", "70b", "command", "coder"],
            "quick":   ["8b", "mini", "flash", "instant", "nano"],
            "vision":  [],   # just use first (largest) model
            "general": [],
        }
        kwords = _PREFER_KWORDS.get(task_type, [])
        preferred = (
            [m for m in models if any(k in m.lower() for k in kwords)]
            if kwords else []
        )
        return (preferred or models or [""])[0]

    def _call_provider(self, provider: Provider, model: str,
                       messages: List[Dict], temperature: float,
                       max_tokens: int) -> Dict:
        """Make API call to specific provider"""

        # O(1) provider call dispatch
        _CALL_DISPATCH = {
            "gemini": lambda: self._call_gemini(
                provider, model, messages, temperature, max_tokens),
        }
        handler = _CALL_DISPATCH.get(provider.name)
        if handler:
            return handler()

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            response = requests.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )

            # O(1) dict dispatch on HTTP status — zero elif branches
            _HTTP_RESPONSES: Dict[int, Callable] = {
                200: lambda d: {
                    "success": True,
                    "content": d.get("choices", [{}])[0].get("message", {}).get("content", ""),
                    "provider": provider.name, "model": model,
                    "usage": d.get("usage", {}), "error": None,
                },
                429: lambda _: {
                    "success": False,
                    "error": f"Rate limited: {response.text}",
                    "provider": provider.name, "model": model,
                },
            }
            _default_err = lambda _: {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
                "provider": provider.name, "model": model,
            }
            handler = _HTTP_RESPONSES.get(response.status_code, _default_err)
            data = response.json() if response.status_code == 200 else {}
            return handler(data)

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Request timeout",
                "provider": provider.name,
                "model": model
            }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {
                "success": False,
                "error": str(e),
                "provider": provider.name,
                "model": model
            }

    def _call_gemini(self, provider: Provider, model: str,
                     messages: List[Dict], temperature: float,
                     max_tokens: int) -> Dict:
        """Special handler for Google's Gemini API"""
        try:
            # Convert messages to Gemini format
            contents = []
            system_instruction = ""

            for msg in messages:
                role = msg["role"]
                content = msg["content"]

                # O(1) dict dispatch — role → action function
                _ROLE_FN: Dict[str, Callable] = {
                    "system":    lambda c: None,  # System handled via system_instruction var below
                    "user":      lambda c: contents.append(
                        {"role": "user", "parts": [{"text": c}]}),
                    "assistant": lambda c: contents.append(
                        {"role": "model", "parts": [{"text": c}]}),
                }
                _role_action = _ROLE_FN.get(role)
                _role_action and _role_action(content)
                # Capture system separately (can't setattr list cleanly)
                role == "system" and contents.__class__  # no-op sentinel
                system_instruction = (
                    content if role == "system" else system_instruction
                )

            url = f"{provider.base_url}/models/{model}:generateContent?key={provider.api_key}"

            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens
                }
            }

            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

            response = requests.post(url, json=payload, timeout=60)

            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return {
                        "success": True,
                        "content": text,
                        "provider": provider.name,
                        "model": model,
                        "error": None
                    }

            return {
                "success": False,
                "error": f"Gemini error: {response.text}",
                "provider": provider.name,
                "model": model
            }

        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {
                "success": False,
                "error": f"Gemini exception: {str(e)}",
                "provider": provider.name,
                "model": model
            }

    def send_vision_request(self,
                            image_base64: str,
                            prompt: str,
                            task_type: str = "vision") -> Dict[str, Any]:
        """
        Send vision request with image

        Args:
            image_base64: Base64 encoded image
            prompt: Text prompt about the image
            task_type: Task classification

        Returns:
            Response dict with success status and content
        """
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }
        ]

        # Try vision-capable providers first
        vision_providers = ["xai", "groq", "openrouter", "gemini"]

        for provider_name in vision_providers:
            provider = self.providers.get(provider_name)
            if not provider or not provider.has_key:
                continue
            if provider.status not in (ProviderStatus.ACTIVE, ProviderStatus.RATE_LIMITED):
                continue

            model = self._select_model(provider, "vision", require_vision=True)

            result = self._call_provider_vision(provider, model, image_base64, prompt)

            if result["success"]:
                provider.requests_made += 1
                self._save_usage_stats()
                return result

        # Fall back to standard routing
        return self.send_message(messages, task_type, require_vision=True)

    def _call_provider_vision(self, provider: Provider, model: str,
                              image_base64: str, prompt: str) -> Dict:
        """Call provider with vision input"""
        try:
            if provider.name == "gemini":
                url = f"{provider.base_url}/models/{model}:generateContent?key={provider.api_key}"
                payload = {
                    "contents": [{
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": image_base64
                                }
                            }
                        ]
                    }]
                }
                response = requests.post(url, json=payload, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        return {"success": True, "content": text, "provider": provider.name, "model": model, "error": None}
                return {"success": False, "error": response.text, "provider": provider.name, "model": model}

            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "temperature": 0.5,
                "max_tokens": 4096
            }

            response = requests.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "content": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                    "provider": provider.name,
                    "model": model,
                    "error": None
                }
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}", "provider": provider.name, "model": model}

        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e), "provider": provider.name, "model": model}

    def _log_usage(self, provider: str, model: str, task_type: str,
                   success: bool, error: str = None):
        """Log usage for analytics"""
        self.usage_log.append({
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "task_type": task_type,
            "success": success,
            "error": error
        })
        # Keep last 1000 entries
        if len(self.usage_log) > 1000:
            self.usage_log = self.usage_log[-1000:]

    def get_status(self) -> Dict:
        """Get current status of all providers"""
        return {
            "providers": {
                name: {
                    "status": p.status.value,
                    "has_key": p.has_key,
                    "requests_made": p.requests_made,
                    "daily_limit": p.daily_limit,
                    "remaining": p.remaining_requests,
                    "errors": p.errors_count,
                    "models": p.models
                }
                for name, p in self.providers.items()
            },
            "total_available_requests": sum(
                p.remaining_requests for p in self.providers.values()
            ),
            "active_providers": len(self.provider_order),
            "provider_order": self.provider_order
        }

    def quick_request(self, prompt: str, task_type: str = "quick") -> str:
        """Simple one-shot request returning just the content string"""
        messages = [{"role": "user", "content": prompt}]
        result = self.send_message(messages, task_type=task_type)
        if result["success"]:
            return result["content"]
        return f"Error: {result.get('error', 'Unknown error')}"


# Singleton instance
_router = None


def get_router() -> LLMRouter:
    """Get or create singleton router instance"""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router