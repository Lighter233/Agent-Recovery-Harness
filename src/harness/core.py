from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from harness.detectors.base import Detector, FailureSignal
from harness.runtime.config import utc_now_iso
from harness.runtime.context import ACTIVE_RUN_CTX, ACTIVE_TRACE
from harness.runtime.run_context import RunContext, generate_run_id
from harness.runtime.trace import TraceReader, TraceRecorder


# Harness 一次运行的结果
@dataclass(frozen=True)
class RunResult:
    run_id: str
    output: dict[str, Any] | None
    status: str  # "ok" | "failed"
    failure_signals: list[FailureSignal]

    # 是否需要走恢复流程
    @property
    def failed(self) -> bool:
        return self.status == "failed"


# Agent recovery harness 入口：包裹用户 LangGraph，提供 checkpoint + trace + detector
class Harness:
    # graph: 未 compile 的 StateGraph（不要传 checkpointer，由 Harness 接管）
    # run_root: run 目录根，例如 "var/runs"
    # detectors: failure detector 列表，每次 run/resume 结束后顺序执行
    # metadata: 写入 metadata.json 的扩展字段（run_id / created_at 由 Harness 自动添加）
    def __init__(
        self,
        *,
        graph: Any,
        run_root: str | Path = "var/runs",
        detectors: list[Detector] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self._graph = graph
        self._run_root = Path(run_root)
        self._detectors = list(detectors or [])
        self._extra_metadata = dict(metadata or {})

    # 新建一次 run，调 graph.invoke(input)
    def run(self, input: dict[str, Any]) -> RunResult:
        run_id = generate_run_id()
        metadata = {
            "run_id": run_id,
            "created_at": utc_now_iso(),
            **self._extra_metadata,
        }
        run_ctx = RunContext.create(run_id, self._run_root, metadata=metadata)
        return self._execute(run_ctx, input)

    # 恢复已存在的 run；input=None 表示从中断点续跑，否则把 input 作为新 state update
    def resume(self, run_id: str, input: dict[str, Any] | None = None) -> RunResult:
        run_ctx = RunContext.resume(run_id, self._run_root)
        return self._execute(run_ctx, input)

    # 上下文管理器收尾，目前是 no-op（每次 run/resume 自己关资源）
    def close(self) -> None:
        pass

    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # run/resume 的共用骨架：装 SqliteSaver、设 ContextVar、跑 detector
    def _execute(self, run_ctx: RunContext, input: dict[str, Any] | None) -> RunResult:
        trace = TraceRecorder(run_ctx.trace_path, run_ctx.run_id)
        db_path = run_ctx.checkpoints_dir / "state.sqlite"
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            saver = SqliteSaver(conn)
            saver.setup()
            compiled = self._graph.compile(checkpointer=saver)
            output, status = self._invoke(compiled, run_ctx, trace, input)
            signals = self._run_detectors(trace)
            if signals:
                status = "failed"
            return RunResult(
                run_id=run_ctx.run_id,
                output=output,
                status=status,
                failure_signals=signals,
            )
        finally:
            conn.close()
            trace.close()

    # 真正跑 graph，期间设好 ACTIVE_TRACE / ACTIVE_RUN_CTX，让节点装饰器和 LLMClient 能读到
    def _invoke(
        self,
        compiled: Any,
        run_ctx: RunContext,
        trace: TraceRecorder,
        input: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, str]:
        graph_config = {"configurable": {"thread_id": run_ctx.run_id}}
        trace_token = ACTIVE_TRACE.set(trace)
        run_ctx_token = ACTIVE_RUN_CTX.set(run_ctx)
        try:
            output = compiled.invoke(input, graph_config)
            return output, "ok"
        except Exception:
            return None, "failed"
        finally:
            ACTIVE_RUN_CTX.reset(run_ctx_token)
            ACTIVE_TRACE.reset(trace_token)

    # 逐个跑 detector，命中写一条 failure_detected event
    def _run_detectors(self, trace: TraceRecorder) -> list[FailureSignal]:
        if not self._detectors:
            return []
        reader = TraceReader(trace.trace_path)
        signals: list[FailureSignal] = []
        for detector in self._detectors:
            signal = detector.inspect(reader)
            if signal is None:
                continue
            signals.append(signal)
            trace.event(
                "failure_detected",
                node=signal.node,
                data={
                    "detector": detector.name,
                    "failure_type": signal.failure_type,
                    "evidence_step_ids": signal.evidence_step_ids,
                    "summary": signal.summary,
                    "raw": signal.raw,
                },
            )
        return signals
