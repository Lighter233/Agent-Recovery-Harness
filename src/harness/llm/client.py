from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from harness.runtime.config import env_override, load_config
from harness.runtime.context import ACTIVE_TRACE, CURRENT_NODE


DEFAULT_SYSTEM_PROMPT = "You are a concise assistant. Reply in Chinese."
DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompt" / "reply" / "system.md"
ChatMessage = dict[str, str]


# LLM 调用配置
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


# OpenAI-compatible chat completions 客户端
class LLMClient:
    # 保存配置和默认 system prompt
    def __init__(self, config: LLMConfig, system_prompt: str = DEFAULT_SYSTEM_PROMPT):
        self.config = config
        self.system_prompt = system_prompt

    # 发送用户问题和可选历史上下文。trace 通过 ACTIVE_TRACE / CURRENT_NODE 自动接入当前 Harness run。
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
            start = time.perf_counter()
            trace = ACTIVE_TRACE.get()
            if trace is not None:
                trace.event(
                    "llm_call",
                    node=CURRENT_NODE.get(),
                    data={"model": self.config.name, "messages_count": len(messages)},
                )
            try:
                answer = self._chat_completion(payload)
                if trace is not None:
                    trace.event(
                        "llm_response",
                        node=CURRENT_NODE.get(),
                        data={"model": self.config.name, "chars": len(answer)},
                        elapsed_ms=(time.perf_counter() - start) * 1000,
                    )
                return answer
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                error = f"HTTP error {exc.code}: {body}"
                self._record_llm_error(attempt, "HTTPError", error, start)
            except (URLError, TimeoutError) as exc:
                error = f"Network error: {exc}"
                self._record_llm_error(attempt, type(exc).__name__, error, start)
            except Exception as exc:
                error = f"LLM error: {exc}"
                self._record_llm_error(attempt, type(exc).__name__, error, start)

            if attempt < attempts:
                time.sleep(1)

        raise RuntimeError(error)

    # 记录单次 LLM 调用失败
    def _record_llm_error(self, attempt: int, exc_type: str, exc_message: str, start: float) -> None:
        trace = ACTIVE_TRACE.get()
        if trace is None:
            return
        trace.event(
            "llm_error",
            node=CURRENT_NODE.get(),
            data={
                "model": self.config.name,
                "attempt": attempt,
                "exc_type": exc_type,
                "exc_message": exc_message[:500],
            },
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )

    # 调用 OpenAI-compatible chat completions 接口
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


# 加载本地 .env，不覆盖已有环境变量
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


# 根据配置文件初始化 LLM 客户端
def init_llm_client(
    config_path: Path,
    dotenv_path: Path | None = None,
    system_prompt_path: Path | None = DEFAULT_SYSTEM_PROMPT_PATH,
) -> LLMClient:
    if dotenv_path is not None:
        load_dotenv(dotenv_path)
    config = load_config(config_path)
    llm_config = _resolve_model_config(config)
    system_prompt = load_prompt(system_prompt_path, DEFAULT_SYSTEM_PROMPT)
    return LLMClient(llm_config, system_prompt=system_prompt)


# 读取 prompt 文件，缺失或为空时使用默认值
def load_prompt(path: Path | None, default: str) -> str:
    if path is None or not path.exists():
        return default
    content = path.read_text(encoding="utf-8").strip()
    return content or default


# 解析当前 provider 的最终模型配置
def _resolve_model_config(config: dict[str, Any]) -> LLMConfig:
    model_config = config["model"]
    provider_name = env_override(model_config, "provider")
    providers = model_config.get("providers", {})
    if provider_name not in providers:
        available = ", ".join(sorted(providers))
        raise ValueError(f"Unknown model provider: {provider_name}. Available: {available}")

    provider = dict(providers[provider_name])
    api_key_env = provider.get("api_key_env")
    api_key_from_env = os.getenv(api_key_env) if api_key_env else None
    api_key = api_key_from_env or provider.get("api_key")
    if not api_key:
        raise RuntimeError(
            f"Missing API key for provider '{provider_name}'. "
            f"Set environment variable {api_key_env!r}."
        )

    return LLMConfig(
        provider=provider_name,
        name=env_override(provider, "name"),
        api_key=api_key,
        base_url=env_override(provider, "base_url").rstrip("/"),
        temperature=model_config.get("temperature", 0),
        request_timeout_sec=provider.get(
            "request_timeout_sec", model_config.get("request_timeout_sec", 90)
        ),
        max_retries=model_config.get("max_retries", 1),
        max_tokens=provider.get("max_tokens", model_config.get("max_tokens", 2048)),
    )
