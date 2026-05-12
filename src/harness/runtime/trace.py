from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from harness.runtime.config import utc_now_iso


# Trace 事件记录器
class TraceRecorder:
    # 打开 trace 文件并初始化 step_id
    def __init__(self, trace_path: Path, run_id: str):
        self.trace_path = trace_path
        self.run_id = run_id
        self.step_id = self._load_last_step_id()
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = trace_path.open("a", encoding="utf-8")

    # 写入一条 trace 事件并立即 flush
    def event(
        self,
        kind: str,
        *,
        node: str | None = None,
        data: dict[str, Any] | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        self.step_id += 1
        event = {
            "ts": utc_now_iso(),
            "run_id": self.run_id,
            "step_id": self.step_id,
            "node": node,
            "kind": kind,
            "data": data or {},
            "elapsed_ms": elapsed_ms,
        }
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._file.flush()

    # 关闭 trace 文件句柄
    def close(self) -> None:
        self._file.close()

    # 读取已有 trace 的最后 step_id
    def _load_last_step_id(self) -> int:
        if not self.trace_path.exists():
            return 0

        last_step_id = 0
        for line in self.trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_step_id = max(last_step_id, int(event.get("step_id", 0)))
        return last_step_id


# 构造异常事件的 data 字段
def error_data(exc: Exception) -> dict[str, Any]:
    return {
        "exc_type": type(exc).__name__,
        "exc_message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


# Trace 事件读取器
class TraceReader:
    # 保存 trace 文件路径
    def __init__(self, trace_path: Path):
        self.trace_path = trace_path

    # 读取最近 n 条 trace 事件
    def tail(self, n: int) -> list[dict[str, Any]]:
        events = self.all()
        return events[-n:]

    # 读取全部 trace 事件
    def all(self) -> list[dict[str, Any]]:
        if not self.trace_path.exists():
            return []

        events = []
        for line in self.trace_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events
