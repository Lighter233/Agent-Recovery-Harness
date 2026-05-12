from __future__ import annotations

import asyncio
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Callable, TypedDict

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings(
    "ignore",
    category=LangChainPendingDeprecationWarning,
)

from langgraph.graph import END, START, StateGraph


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from harness.runtime.context import CURRENT_NODE


# Spike 图状态
class SpikeState(TypedDict, total=False):
    query: str
    plan: str
    answer: str
    seen_node: str | None


# 生成占位 plan
def plan_node(state: SpikeState) -> SpikeState:
    return {"plan": f"reply to: {state['query']}"}


# 成功回复节点
def reply_ok_node(state: SpikeState) -> SpikeState:
    return {"answer": f"ok: {state['plan']}"}


# 失败回复节点
def reply_fail_node(state: SpikeState) -> SpikeState:
    raise RuntimeError("spike boom in reply")


# 读取当前 ContextVar 的探针节点
def context_probe_node(state: SpikeState) -> SpikeState:
    return {"seen_node": CURRENT_NODE.get()}


# 构建最小两节点图
def build_graph(reply_node: Callable[[SpikeState], SpikeState]):
    graph = StateGraph(SpikeState)
    graph.add_node("plan", plan_node)
    graph.add_node("reply", reply_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "reply")
    graph.add_edge("reply", END)
    return graph.compile()


# 构建 ContextVar 探针图
def build_context_probe_graph():
    graph = StateGraph(SpikeState)
    graph.add_node("probe", context_probe_node)
    graph.add_edge(START, "probe")
    graph.add_edge("probe", END)
    return graph.compile()


# 将事件转成可打印 JSON
def format_event(event: Any) -> str:
    return json.dumps(event, ensure_ascii=False, default=str)


# 打印同步 stream 事件
def print_stream_mode(graph, mode: str, *, should_fail: bool) -> None:
    label = "fail" if should_fail else "ok"
    print(f"\n=== stream_mode={mode} / {label} ===")
    try:
        for index, event in enumerate(
            graph.stream({"query": "hi"}, stream_mode=mode),
            start=1,
        ):
            print(f"{index}: {format_event(event)}")
    except Exception as exc:
        print(f"EXCEPTION: {type(exc).__name__}: {exc}")


# 打印 astream_events 事件
async def print_astream_events(graph, *, should_fail: bool) -> None:
    label = "fail" if should_fail else "ok"
    print(f"\n=== astream_events / {label} ===")
    if not hasattr(graph, "astream_events"):
        print("NOT_AVAILABLE")
        return

    try:
        try:
            stream = graph.astream_events({"query": "hi"}, version="v2")
        except TypeError:
            stream = graph.astream_events({"query": "hi"})

        async for index, event in async_enumerate(stream, start=1):
            print(f"{index}: {format_event(event)}")
    except Exception as exc:
        print(f"EXCEPTION: {type(exc).__name__}: {exc}")


# 验证事件消费者设置 CURRENT_NODE 是否能被节点内部读取
async def print_context_probe() -> None:
    print("\n=== contextvar probe with astream_events ===")
    graph = build_context_probe_graph()
    token = None
    async for event in graph.astream_events({}, version="v2"):
        print(format_event(event))
        if event.get("event") == "on_chain_start" and event.get("name") == "probe":
            token = CURRENT_NODE.set("probe")
        if event.get("event") == "on_chain_end" and event.get("name") == "probe" and token:
            CURRENT_NODE.reset(token)


# 异步枚举 helper
async def async_enumerate(stream, start: int = 1):
    index = start
    async for item in stream:
        yield index, item
        index += 1


# 跑完所有 stream API 组合
async def main() -> None:
    ok_graph = build_graph(reply_ok_node)
    fail_graph = build_graph(reply_fail_node)

    for mode in ["updates", "debug", "values"]:
        print_stream_mode(ok_graph, mode, should_fail=False)
        print_stream_mode(fail_graph, mode, should_fail=True)

    await print_astream_events(ok_graph, should_fail=False)
    await print_astream_events(fail_graph, should_fail=True)
    await print_context_probe()


if __name__ == "__main__":
    asyncio.run(main())
