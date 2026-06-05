from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..config import resolve_dashscope_config


class DashScopeClientError(RuntimeError):
    pass


class DashScopeCompatibleClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None) -> None:
        resolved = resolve_dashscope_config()

        self.api_key = api_key or resolved.get("api_key")
        base_url_value = (
            base_url
            or resolved.get("base_url")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.base_url = str(base_url_value).rstrip("/")
        self.model = model or resolved.get("model") or "qwen-3.5-plus"
        self.fallback_model = "qwen3.5-plus"
        timeout = resolved.get("timeout_seconds")
        self.timeout_seconds = int(timeout) if isinstance(timeout, int) and timeout > 0 else 45
        if not self.api_key:
            config_path = resolved.get("config_path")
            raise DashScopeClientError(
                f"Missing DASHSCOPE_API_KEY (env) and api_key in {config_path}"
            )

    def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise DashScopeClientError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise DashScopeClientError(f"Request failed: {exc}") from exc

    def chat_json(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            result = self._request(payload)
        except DashScopeClientError as err:
            should_retry = self.model != self.fallback_model and (
                "model" in str(err).lower() or "not found" in str(err).lower()
            )
            if not should_retry:
                raise
            payload["model"] = self.fallback_model
            result = self._request(payload)

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
            content = "\n".join(text_parts)
        return str(content)


def extract_json_block(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    brace_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError("No JSON object found")
