from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from harness.runtime.trace import TraceReader


# 失败检测结果
@dataclass(frozen=True)
class FailureSignal:
    failure_type: str
    node: str | None
    evidence_step_ids: list[int]
    summary: str
    # 只放结构化轻量字段，禁止内嵌完整 trace 事件
    raw: dict


# Detector 接口
class Detector(Protocol):
    name: str

    # 检查 trace 并返回一个失败信号
    def inspect(self, reader: TraceReader) -> FailureSignal | None:
        ...
