from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from harness import InjectedFailure, clear_injections, inject_failure, traced_node
from harness.detectors.exception import ExceptionDetector
from harness.runtime.config import env_override
from harness.runtime.context import ACTIVE_TRACE, CURRENT_NODE
from harness.runtime.trace import TraceReader, TraceRecorder


# Runtime 核心逻辑测试
class RuntimeCoreTest(unittest.TestCase):
    # 每个用例之间清空失败注入，避免互相干扰
    def setUp(self) -> None:
        clear_injections()

    def tearDown(self) -> None:
        clear_injections()

    # 测试空环境变量不会覆盖 YAML 默认值
    def test_env_override_ignores_empty_env(self) -> None:
        old_value = os.environ.get("MODEL_PROVIDER")
        os.environ["MODEL_PROVIDER"] = ""
        try:
            value = env_override(
                {"provider": "aliyun", "provider_env": "MODEL_PROVIDER"},
                "provider",
            )
        finally:
            if old_value is None:
                os.environ.pop("MODEL_PROVIDER", None)
            else:
                os.environ["MODEL_PROVIDER"] = old_value

        self.assertEqual(value, "aliyun")

    # 测试 traced_node 会写 node_enter/node_exit、设置/恢复 CURRENT_NODE
    def test_traced_node_writes_events_and_manages_current_node(self) -> None:
        captured: list[str | None] = []

        @traced_node("worker")
        def step(state: dict) -> dict:
            captured.append(CURRENT_NODE.get())
            return {"value": state["value"] + 1}

        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "trace.jsonl"
            recorder = TraceRecorder(trace_path, "test")
            token = ACTIVE_TRACE.set(recorder)
            try:
                result = step({"value": 1})
            finally:
                ACTIVE_TRACE.reset(token)
                recorder.close()
            events = TraceReader(trace_path).all()

        self.assertEqual(result, {"value": 2})
        self.assertEqual(captured, ["worker"])
        self.assertIsNone(CURRENT_NODE.get())
        self.assertEqual([e["kind"] for e in events], ["node_enter", "node_exit"])

    # 测试节点未在 Harness 下执行时，traced_node 退化为透传
    def test_traced_node_passthrough_when_no_active_trace(self) -> None:
        @traced_node("worker")
        def step(state: dict) -> dict:
            return state

        self.assertIsNone(ACTIVE_TRACE.get())
        self.assertEqual(step({"x": 1}), {"x": 1})

    # 测试 inject_failure 会在目标 visit 触发，之后不再触发
    def test_inject_failure_fires_only_at_target_visit(self) -> None:
        @traced_node("step")
        def step(state: dict) -> dict:
            return state

        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "trace.jsonl"
            recorder = TraceRecorder(trace_path, "test")
            token = ACTIVE_TRACE.set(recorder)
            try:
                inject_failure(node="step", visit=2)
                self.assertEqual(step({"a": 1}), {"a": 1})
                with self.assertRaises(InjectedFailure):
                    step({"a": 1})
                # visit 已用完，第 3 次不再触发
                self.assertEqual(step({"a": 1}), {"a": 1})
            finally:
                ACTIVE_TRACE.reset(token)
                recorder.close()

    # 测试 ExceptionDetector 只返回轻量 raw 字段
    def test_exception_detector_returns_lightweight_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "trace.jsonl"
            recorder = TraceRecorder(trace_path, "test")
            recorder.event(
                "error",
                node="reply",
                data={"exc_type": "RuntimeError", "exc_message": "boom", "traceback": "large"},
            )
            recorder.close()

            signal = ExceptionDetector().inspect(TraceReader(trace_path))

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.failure_type, "runtime_error")
        self.assertEqual(signal.evidence_step_ids, [1])
        self.assertEqual(signal.raw, {"exc_type": "RuntimeError", "exc_message": "boom"})

    # 测试 TraceRecorder 从已有 trace 继续递增 step_id
    def test_trace_recorder_resumes_step_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "trace.jsonl"
            first = TraceRecorder(trace_path, "test")
            first.event("node_enter", node="plan")
            first.close()

            second = TraceRecorder(trace_path, "test")
            second.event("node_exit", node="plan")
            second.close()

            events = TraceReader(trace_path).all()

        self.assertEqual([event["step_id"] for event in events], [1, 2])


if __name__ == "__main__":
    unittest.main()
