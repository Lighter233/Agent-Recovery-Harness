from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.runtime.run_context import RunContext
    from harness.runtime.trace import TraceRecorder


# 当前正在执行的 LangGraph 节点名，由 @traced_node 在节点入口处设置
CURRENT_NODE: ContextVar[str | None] = ContextVar("CURRENT_NODE", default=None)

# 当前 Harness 运行的 trace 记录器，由 Harness 在调用 graph.invoke 前设置
ACTIVE_TRACE: ContextVar["TraceRecorder | None"] = ContextVar("ACTIVE_TRACE", default=None)

# 当前 Harness 运行的 RunContext，由 Harness 在调用 graph.invoke 前设置
ACTIVE_RUN_CTX: ContextVar["RunContext | None"] = ContextVar("ACTIVE_RUN_CTX", default=None)
