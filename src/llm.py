from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


DEFAULT_SYSTEM_PROMPT = "You are a concise assistant. Reply in Chinese."
ChatMessage = dict[str, str]


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    name: str
    api_key: str
    base_url: str
    temperature: float
    request_timeout_sec: int
    max_retries: int
    max_tokens: int


class LLMClient:
    # 保存已经解析好的 LLM 配置，供后续请求复用。
    def __init__(self, config: LLMConfig, system_prompt: str = DEFAULT_SYSTEM_PROMPT):
        self.config = config
        self.system_prompt = system_prompt

    # 发送用户问题和可选历史上下文，并返回模型文本回答。
    def chat(
        self,
        query: str,
        history: list[ChatMessage] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        system_prompt = system_prompt or self.system_prompt
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        payload = {
            "model": self.config.name,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        attempts = self.config.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return self._chat_completion(payload)
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                error = f"HTTP error {exc.code}: {body}"
            except (URLError, TimeoutError) as exc:
                error = f"Network error: {exc}"
            except Exception as exc:
                error = f"LLM error: {exc}"

            if attempt < attempts:
                time.sleep(1)

        raise RuntimeError(error)

    # 调用 OpenAI-compatible chat completions 接口。
    def _chat_completion(self, payload: dict[str, Any]) -> str:
        url = f"{self.config.base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlopen(request, timeout=self.config.request_timeout_sec) as response:
            raw = response.read().decode("utf-8")

        result = json.loads(raw)
        return result["choices"][0]["message"]["content"]


# 从本地 .env 文件加载环境变量，但不覆盖已有环境变量。
def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


# 根据配置文件和本地环境变量初始化 LLM 客户端。
def init_llm_client(
    config_path: Path,
    dotenv_path: Path | None = None,
    system_prompt_path: Path | None = None,
) -> LLMClient:
    if dotenv_path is not None:
        load_dotenv(dotenv_path)

    config = _load_yaml(config_path)
    llm_config = _resolve_model_config(config)
    system_prompt = load_prompt(system_prompt_path, DEFAULT_SYSTEM_PROMPT)
    return LLMClient(llm_config, system_prompt=system_prompt)


# 从 prompt 文件读取内容，文件不存在或为空时使用默认值。
def load_prompt(path: Path | None, default: str) -> str:
    if path is None or not path.exists():
        return default

    content = path.read_text(encoding="utf-8").strip()
    return content or default


# 读取 YAML 配置文件，并确保顶层是对象。
def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a YAML object: {path}")
    return config


# 读取配置值，并优先使用配置中声明的环境变量覆盖。
def _env_override(config: dict[str, Any], key: str, default: Any = None) -> Any:
    value = config.get(key, default)
    env_key = config.get(f"{key}_env")
    if env_key and os.getenv(env_key):
        return os.environ[env_key]
    return value


# 解析当前 model provider 的最终运行配置。
def _resolve_model_config(config: dict[str, Any]) -> LLMConfig:
    model_config = config["model"]
    provider_name = _env_override(model_config, "provider")
    providers = model_config.get("providers", {})
    if provider_name not in providers:
        available = ", ".join(sorted(providers))
        raise ValueError(f"Unknown model provider: {provider_name}. Available: {available}")

    provider = dict(providers[provider_name])
    api_key_env = provider.get("api_key_env")
    api_key = os.getenv(api_key_env) if api_key_env else provider.get("api_key")
    if not api_key:
        raise RuntimeError(
            f"Missing API key for provider '{provider_name}'. "
            f"Set environment variable {api_key_env!r}."
        )

    return LLMConfig(
        provider=provider_name,
        name=_env_override(provider, "name"),
        api_key=api_key,
        base_url=_env_override(provider, "base_url").rstrip("/"),
        temperature=model_config.get("temperature", 0),
        request_timeout_sec=provider.get(
            "request_timeout_sec", model_config.get("request_timeout_sec", 90)
        ),
        max_retries=model_config.get("max_retries", 1),
        max_tokens=provider.get("max_tokens", model_config.get("max_tokens", 2048)),
    )
