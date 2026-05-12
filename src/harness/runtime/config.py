from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# YAML 配置读取
def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a YAML object: {config_path}")
    return config


# 环境变量优先级处理
def env_override(config: dict[str, Any], key: str, default: Any = None) -> Any:
    value = config.get(key, default)
    env_key = config.get(f"{key}_env")
    env_value = os.getenv(env_key) if env_key else None
    if env_value:
        return env_value
    return value


# 生成 UTC ISO 时间
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# run_root 路径解析
def resolve_run_root(config: dict[str, Any], project_root: Path) -> Path:
    run_root = config.get("paths", {}).get("run_root", "var/runs")
    path = Path(run_root)
    if not path.is_absolute():
        path = project_root / path
    return path


# Run metadata 构建。run_id 和 created_at 由 Harness 内部添加。
def build_run_metadata(config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model", {})
    provider = env_override(model_config, "provider", model_config.get("provider"))
    provider_config = model_config.get("providers", {}).get(provider, {})
    model_name = env_override(provider_config, "name", provider_config.get("name"))
    base_url = env_override(provider_config, "base_url", provider_config.get("base_url"))
    max_tokens = provider_config.get("max_tokens", model_config.get("max_tokens", 2048))

    return {
        "provider": provider,
        "model": model_name,
        "config_snapshot": {
            "provider": provider,
            "model": model_name,
            "base_url": base_url,
            "temperature": model_config.get("temperature", 0),
            "max_tokens": max_tokens,
        },
    }
