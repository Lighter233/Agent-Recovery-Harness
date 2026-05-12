from __future__ import annotations

import functools
import time
from typing import Any, Callable

from harness.runtime.context import ACTIVE_TRACE, CURRENT_NODE
from harness.runtime.trace import error_data
from harness.testing.injection import _maybe_inject


# 装饰用户的 LangGraph 节点函数。
# 节点执行期间：
#   - 写 node_enter / node_exit / error 到 trace
#   - 设置 CURRENT_NODE，使节点内部调用的 LLMClient 能把事件标到该节点
#   - 调 _maybe_inject，命中时抛 InjectedFailure（会被记成 error 事件）
# Harness 未运行时（例如单测直接调节点函数），装饰器只做注入检查，不写 trace。
def traced_node(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace = ACTIVE_TRACE.get()
            if trace is None:
                _maybe_inject(name)
                return fn(*args, **kwargs)

            token = CURRENT_NODE.set(name)
            start = time.perf_counter()
            trace.event("node_enter", node=name)
            try:
                _maybe_inject(name)
                result = fn(*args, **kwargs)
            except Exception as exc:
                trace.event("error", node=name, data=error_data(exc))
                raise
            else:
                elapsed_ms = (time.perf_counter() - start) * 1000
                trace.event("node_exit", node=name, data={"ok": True}, elapsed_ms=elapsed_ms)
                return result
            finally:
                CURRENT_NODE.reset(token)

        return wrapper

    return decorator
