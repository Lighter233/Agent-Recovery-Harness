from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)

from harness import ExceptionDetector, Harness, RunResult
from harness.llm.client import init_llm_client, load_dotenv
from harness.runtime.config import build_run_metadata, load_config, resolve_run_root

from graph import build_chat_graph


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# CLI 参数解析
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agent Recovery Harness chat demo",
        epilog=(
            "Examples:\n"
            "  python src/main.py --query hi\n"
            "  python src/main.py --resume <run_id> --query '刚刚我问了什么'\n"
            "  python src/main.py --resume <run_id> --continue-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--dotenv", default=str(PROJECT_ROOT / ".env"))
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--query")
    parser.add_argument("--continue-run", action="store_true")
    args = parser.parse_args()

    if args.continue_run and not args.resume:
        parser.error("--continue-run requires --resume RUN_ID")
    if args.continue_run and args.query:
        parser.error("--continue-run cannot be combined with --query")
    if not args.resume and not args.query:
        parser.error("provide --query for a new run, or --resume RUN_ID")

    return args


# 主入口：构造 Harness，跑一次 run 或 resume
def main() -> int:
    args = parse_args()
    load_dotenv(Path(args.dotenv))
    try:
        client = init_llm_client(Path(args.config))
        config = load_config(Path(args.config))
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
        if args.continue_run:
            result = harness.resume(args.resume)
        elif args.resume:
            result = harness.resume(args.resume, input={"query": args.query})
        else:
            result = harness.run({"query": args.query})

    print(f"run_id: {result.run_id}")
    return _print_result(result)

# 打印一次 run 的最终结果，返回退出码
def _print_result(result: RunResult) -> int:
    if result.failed:
        if result.failure_signals:
            print(f"Failed: {result.failure_signals[0].summary}", file=sys.stderr)
        else:
            print("Failed: see trace.jsonl for details", file=sys.stderr)
        return 1

    if result.output is None:
        print("No output", file=sys.stderr)
        return 1

    answer = result.output.get("answer", "")
    if answer:
        print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
