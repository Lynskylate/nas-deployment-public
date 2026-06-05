from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import tomllib


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "cigbutt" / "config.toml"


def resolve_config_path(config_path: Optional[str] = None) -> Path:
    if config_path:
        return Path(config_path).expanduser()

    from_env = os.getenv("CIGBUTT_CONFIG_FILE")
    if from_env:
        return Path(from_env).expanduser()

    return DEFAULT_CONFIG_PATH


def load_toml_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = resolve_config_path(config_path)
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return str(value)
    return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def resolve_dashscope_config(
    config_path: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    env_map = dict(os.environ if env is None else env)
    payload = load_toml_config(config_path=config_path)
    dashscope_table = _as_dict(payload.get("dashscope"))
    llm_dashscope_table = _as_dict(_as_dict(payload.get("llm")).get("dashscope"))

    file_api_key = _first_non_empty(
        dashscope_table.get("api_key"),
        llm_dashscope_table.get("api_key"),
        payload.get("dashscope_api_key"),
    )
    file_base_url = _first_non_empty(
        dashscope_table.get("base_url"),
        llm_dashscope_table.get("base_url"),
        payload.get("dashscope_base_url"),
    )
    file_model = _first_non_empty(
        dashscope_table.get("model"),
        llm_dashscope_table.get("model"),
        payload.get("dashscope_model"),
    )
    file_timeout = _safe_int(
        _first_non_empty(
            dashscope_table.get("timeout_seconds"),
            llm_dashscope_table.get("timeout_seconds"),
            payload.get("dashscope_timeout_seconds"),
        )
    )

    env_api_key = _first_non_empty(env_map.get("DASHSCOPE_API_KEY"))
    env_base_url = _first_non_empty(env_map.get("DASHSCOPE_BASE_URL"))
    env_model = _first_non_empty(env_map.get("DASHSCOPE_MODEL"))
    env_timeout = _safe_int(_first_non_empty(env_map.get("DASHSCOPE_TIMEOUT_SECONDS")))

    return {
        "api_key": _first_non_empty(env_api_key, file_api_key),
        "base_url": _first_non_empty(env_base_url, file_base_url),
        "model": _first_non_empty(env_model, file_model),
        "timeout_seconds": env_timeout if env_timeout is not None else file_timeout,
        "config_path": str(resolve_config_path(config_path)),
    }
