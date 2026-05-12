from __future__ import annotations

import sys
import warnings
from pathlib import Path

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from harness import ExceptionDetector, Harness, RunResult, inject_failure
from harness.llm.client import init_llm_client, load_dotenv
from harness.runtime.config import build_run_metadata, load_config, resolve_run_root
from harness.runtime.trace import TraceReader

from graph import build_chat_graph


# 单进程跑一次"注入失败 → 从 checkpoint 续跑"演示
def main() -> int:
    config_path = PROJECT_ROOT / "config" / "config.yaml"
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        client = init_llm_client(config_path)
        config = load_config(config_path)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    run_root = resolve_run_root(config, PROJECT_ROOT)
    graph = build_chat_graph(client)

    with Harness(
        graph=graph,
        run_root=run_root,
        detectors=[ExceptionDetector()],
        metadata=build_run_metadata(config),
    ) as harness:
        # 第一次：注入失败，预期 reply 第一次进入时抛 InjectedFailure
        inject_failure(node="reply", visit=1)
        first = harness.run({"query": "hi"})
        if not first.failed:
            print("Expected first run to fail, but it succeeded.", file=sys.stderr)
            return 1

        # 第二次：同 run_id 续跑。注入计数已经"用过"，不会再触发。
        second = harness.resume(first.run_id)
        if second.failed:
            print(f"Resume failed: {second.failure_signals}", file=sys.stderr)
            return 1

    _print_timeline(first, second)
    return 0


# 从 trace 生成"先失败后恢复"的人类可读时间线
def _print_timeline(first: RunResult, second: RunResult) -> None:
    trace_path = _resolve_trace_path(first.run_id)
    events = TraceReader(trace_path).all()

    print(f"run_id: {first.run_id}")
    step = 0
    failed_steps: dict[str, int] = {}
    for event in events:
        kind = event.get("kind")
        node = event.get("node") or ""
        if kind == "node_enter":
            step += 1
            continue
        if kind == "node_exit":
            if node in failed_steps:
                print("[recovery] resuming from checkpoint")
                print(f"[step {failed_steps[node]}'] {node} OK")
            else:
                print(f"[step {step}] {node} OK")
        elif kind == "error":
            failed_steps[node] = step
            summary = _error_summary(event)
            print(f"[step {step}] {node} FAILED: {summary}")
    print("DONE. Recovered from checkpoint.")


# 从 error 事件读出简短摘要
def _error_summary(event: dict) -> str:
    data = event.get("data", {})
    if not isinstance(data, dict):
        return "unknown failure"
    exc_type = str(data.get("exc_type", "Exception"))
    exc_message = str(data.get("exc_message", "")).strip()
    return f"{exc_type}: {exc_message}" if exc_message else exc_type


# 用 run_id 反查 trace 文件路径
def _resolve_trace_path(run_id: str) -> Path:
    config_path = PROJECT_ROOT / "config" / "config.yaml"
    config = load_config(config_path)
    run_root = resolve_run_root(config, PROJECT_ROOT)
    return run_root / run_id / "trace.jsonl"


if __name__ == "__main__":
    sys.exit(main())
