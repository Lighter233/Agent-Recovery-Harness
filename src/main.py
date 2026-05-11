from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm import ChatMessage, LLMClient, init_llm_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "src" / "prompt" / "reply" / "system.md"


# 执行一次性问答，适合脚本测试或非交互调用。
def answer_once(client: LLMClient, query: str) -> int:
    try:
        answer = client.chat(query)
    except Exception as exc:
        print(f"LLM error: {exc}", file=sys.stderr)
        return 1

    print(answer)
    return 0


# 启动交互式循环，持续读取用户 query 并输出 answer。
def chat_loop(client: LLMClient) -> int:
    print("Agent Recovery Harness LLM chat")
    print("输入问题开始对话；输入 exit / quit / q 退出。")

    history: list[ChatMessage] = []

    while True:
        try:
            query = input("\nquery> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            return 0

        print("answer> ", end="", flush=True)
        try:
            answer = client.chat(query, history=history)
        except Exception as exc:
            print(f"LLM error: {exc}", file=sys.stderr)
            continue

        print(answer)
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": answer})


# 解析命令行参数，初始化客户端，并选择单轮或交互模式。
def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Recovery Harness interactive chat.")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config" / "config.yaml"),
        help="Path to config.yaml.",
    )
    parser.add_argument(
        "--dotenv",
        default=str(PROJECT_ROOT / ".env"),
        help="Path to local .env file.",
    )
    parser.add_argument(
        "--system-prompt",
        default=str(DEFAULT_SYSTEM_PROMPT_PATH),
        help="Path to the reply system prompt markdown file.",
    )
    parser.add_argument("--query", help="Run one query and exit.")
    args = parser.parse_args()

    try:
        client = init_llm_client(
            Path(args.config),
            Path(args.dotenv),
            Path(args.system_prompt),
        )
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.query:
        return answer_once(client, args.query)

    return chat_loop(client)


if __name__ == "__main__":
    raise SystemExit(main())
