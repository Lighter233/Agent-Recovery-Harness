from __future__ import annotations

from harness.detectors.base import FailureSignal
from harness.runtime.trace import TraceReader


# Runtime exception 检测器
class ExceptionDetector:
    name = "exception_detector"

    # 设置最近事件扫描窗口
    def __init__(self, window: int = 20):
        self.window = window

    # 扫描最近事件中的 error，并忽略已经上报过的 error
    def inspect(self, reader: TraceReader) -> FailureSignal | None:
        events = reader.tail(self.window)
        reported_step_ids = self._reported_error_step_ids(events)

        for event in reversed(events):
            if event.get("kind") != "error":
                continue

            step_id = int(event.get("step_id", 0))
            if step_id in reported_step_ids:
                continue

            data = event.get("data", {})
            if not isinstance(data, dict):
                data = {}
            node = event.get("node")
            exc_type = str(data.get("exc_type", "Exception"))
            exc_message = str(data.get("exc_message", ""))
            return FailureSignal(
                failure_type="runtime_error",
                node=str(node) if node is not None else None,
                evidence_step_ids=[step_id],
                summary=f"{exc_type}: {exc_message}",
                raw={"exc_type": exc_type, "exc_message": exc_message},
            )

        return None

    # 收集已经被 failure_detected 引用过的 error step_id
    def _reported_error_step_ids(self, events: list[dict]) -> set[int]:
        reported = set()
        for event in events:
            if event.get("kind") != "failure_detected":
                continue
            data = event.get("data", {})
            if not isinstance(data, dict):
                continue
            for step_id in data.get("evidence_step_ids", []):
                reported.add(int(step_id))
        return reported
