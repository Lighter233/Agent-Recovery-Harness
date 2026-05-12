# Agent Recovery Harness

一个面向 long-horizon LangGraph agent 的 drop-in 失败恢复层：用户写自己的 graph，把它交给 harness 包一层，自动获得 checkpoint、failure detection、diagnose 和 recovery 策略，而不需要修改 agent 代码本身。

## 一句话问题

长任务 agent 跑到第 12 步挂了，今天常见的选择只有两个：从头再跑，浪费 token、时间和钱；或者直接放弃。现有 agent 框架大多只提供基础状态保存，缺少面向失败诊断和恢复策略的应用层 harness，而每个团队又都要为自己的 agent 重新发明一遍这层逻辑。

## 为什么重要

Long-horizon agent 正在变成主流工作流：background coding agent、research agent、workflow agent、customer support agent 都会连续执行多步任务。但任务越长，失败越常见：

- tool call 参数幻觉或 schema mismatch
- API / browser / shell 等外部工具超时
- agent 原地打转，重复执行相同步骤
- plan drift，执行轨迹偏离原始目标
- 上下文过长导致关键状态丢失

这些失败不应该默认触发"从零重跑"。更合理的做法是：保留执行轨迹，识别失败类型，选择恢复策略，然后从最近 checkpoint 继续。Agent Recovery Harness 把这一层抽出来做成可复用的库，让任何 LangGraph agent 几行代码就能接入。

## 目标用法

用户写自己的 LangGraph，不需要 import harness 任何东西：

```python
# examples/your_agent/agent.py — 用户自己的代码
from langgraph.graph import StateGraph, START, END

def step_one(state): ...
def step_two(state): ...

graph = StateGraph(MyState)
graph.add_node("step_one", step_one)
graph.add_node("step_two", step_two)
graph.add_edge(START, "step_one")
graph.add_edge("step_one", "step_two")
graph.add_edge("step_two", END)
user_graph = graph.compile()  # 不传 checkpointer，由 harness 接管
```

然后用 harness 跑：

```python
from harness import Harness, ExceptionDetector, LoopingDetector

h = Harness(
    graph=user_graph,
    run_root="var/runs",
    detectors=[ExceptionDetector(), LoopingDetector(k=3)],
)

result = h.run({"task": "..."})
if result.failed:
    h.resume(result.run_id)        # 从最近 checkpoint 继续
```

测试时用独立的 testing 模块注入失败，不污染用户代码：

```python
from harness.testing import inject_failure

inject_failure(node="step_two", visit=1)
h.run({"task": "..."})             # step_two 首次会抛 InjectedFailure
```

## 核心模块

Harness 在用户 graph 外面叠四层：

1. **Checkpoint** — 复用 LangGraph 的 SQLite checkpointer，落盘到 `var/runs/{run_id}/checkpoints/`，支持任意 step 恢复。
2. **Trace** — 通过订阅 LangGraph 的 stream events 自动写 `trace.jsonl`，记录 node、LLM、error、failure 事件。用户节点不需要手动埋点。
3. **Failure Detection** — 一组独立 detector（`ExceptionDetector`、`LoopingDetector`、未来的 `ToolHallucinationDetector` / `PlanDriftDetector`）读取 trace，输出结构化 `FailureSignal`。
4. **Diagnose + Recovery**（后续模块）— diagnose subagent 输出根因和策略；recovery executor 选择 retry / fix-and-retry / branch / human-in-the-loop / abort。

## 为什么这是 Harness，而不是 Infra

这个项目的核心不是"把状态写进数据库"，而是 long-horizon agent 的应用层设计决策：

- checkpoint 粒度怎么选：每个 tool call 都存太重，每个语义步骤又需要定义边界
- 怎么判断 agent 卡住：字面重复、语义重复、目标无进展分别如何检测
- plan drift 怎么判断：偏离原计划到底是错误，还是合理的计划修正
- recovery context 怎么注入：完整 trace 太长，summary 又可能丢关键细节
- 什么时候让人介入：不是所有失败都应该自动重试

这些问题决定了 agent 能不能可靠完成长任务，也是 harness 在每个用户场景里需要做出的决策。

## Demo 目标

`examples/` 下提供至少两个形状不同的 user agent，用同一个 harness 跑：

```bash
python -m examples.chat_agent.main --inject-failure reply:1
python -m examples.sql_agent.main --inject-failure execute_sql:1
```

预期输出：

```text
run_id: 20260512_120000_123_abcd
[step 1] generate_sql OK
[step 2] execute_sql FAILED: schema_misuse (column `user_id` does not exist; agent guessed `customer_id`)
[recovery] diagnosing... root_cause: schema_misuse, strategy: fix-and-retry
[step 2'] execute_sql OK (with corrected param)
DONE. Recovered from step 2 failure.
```

README 第一屏最终会放一个 30 秒 demo GIF，展示同一个 harness 跑两个 agent，都能从注入失败中恢复。

## 指标

- **Recovery rate**：注入不同类型失败后，最终成功完成原任务的比例
- **Work saved**：相比从零重跑节省的 token、时间和成本
- **False positive rate**：detector 错把正常执行判成失败的比例
- **Recovery latency**：诊断和恢复本身引入的额外耗时
- **Integration cost**：在一个新 user agent 上接入 harness 需要改的代码行数（目标：< 10）

目标 benchmark：

- 自定义 injected failure suite（覆盖 ≥ 2 个用户场景）
- τ-bench 多步工具调用任务
- SWE-bench mini / long-horizon coding tasks

## 计划架构

```text
src/
  harness/
    __init__.py          # 对外 export：Harness, ExceptionDetector, LoopingDetector, ...
    core.py              # Harness 类：run / resume / wrap user graph
    runtime/
      run_context.py     # run_id、run 目录
      trace.py           # TraceRecorder / TraceReader / event schema
      context.py         # CURRENT_NODE contextvar
    detectors/
      base.py            # Detector protocol, FailureSignal
      exception.py
      looping.py         # 后续
    diagnose/            # 后续
    recovery/            # 后续
    testing/
      injection.py       # inject_failure，从用户代码里隔离测试逻辑
examples/
  chat_agent/            # 现在的 plan→reply demo 搬到这里，作为示例场景 1
  sql_agent/             # 示例场景 2（M5.5 加）
tests/
```

## 路线图

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| M0-M4 | run 目录、SQLite checkpoint、trace、ExceptionDetector、recovery demo | ✅ 已完成 |
| **M4.5** | **抽出 `harness/` 包，把 plan/reply 搬到 `examples/chat_agent/`，trace 改为通过 LangGraph stream events 自动注入** | 进行中 |
| M5 | LoopingDetector（先字面重复，再语义相似度） | |
| M5.5 | 第二个示例场景 `sql_agent`，验证 harness 通用性 | |
| M6 | Diagnose subagent，输出结构化诊断 | |
| M7 | Recovery strategy router + executor | |
| M8 | τ-bench / SWE-bench mini 验证、demo GIF、技术 blog | |

## 面试 Pitch

> 我做了一个 LangGraph agent 的 drop-in recovery layer：用户写自己的 graph，包一层 harness 后自动获得 checkpoint、failure detection、diagnose 和 recovery 策略，接入只需要不到 10 行代码。在 N 个不同形状的 agent 上验证过，针对 timeout / runtime error / looping / plan drift 等失败类型，把任务恢复率从 X% 提到 Y%，相比从零重跑平均节省 Z% 的 token 成本。

## 当前状态

M0-M4 已完成，最小恢复闭环跑通：

1. 每次运行生成毫秒级 + 随机后缀 `run_id` 和独立 run 目录
2. SQLite checkpoint 持久化 LangGraph state，进程重启可 resume
3. `trace.jsonl` 记录 node / LLM / error / failure 事件
4. `ExceptionDetector` 把 runtime exception 转成结构化 `failure_detected`
5. `scripts/recovery_demo.py` 演示 `reply` 失败后从 checkpoint 继续完成
6. LangGraph 节点实现集中在 `src/nodes.py`，`src/graph.py` 只负责接线

**下一步是 M4.5**：把现在内嵌在 `src/` 里的逻辑抽成 `harness/` 包，让外部 LangGraph agent 也能 drop-in 接入；同时把 `plan → reply` 这个 chat demo 搬到 `examples/chat_agent/`，作为 harness 的第一个示例用户场景。

## 开发流程

后续编码按这个节奏推进：

1. **需求分析**：先明确要解决的问题、输入输出、边界条件和验收标准
2. **步骤拆解**：把需求拆成可独立验证的小模块
3. **按模块撰写代码**：先写核心路径，保持模块职责清楚
4. **最小 MVP 实现**：优先跑通闭环，再逐步补边界能力
5. **自检查测试**：每次改动后做语法检查、关键路径运行和必要的 smoke test
6. **撰写文档**：更新 README 或模块说明，记录运行方式和设计选择

代码约定：每个函数或类方法前写一行简短注释，说明它负责什么。

## 运行示例 chat agent

`examples/chat_agent` 是 harness 的第一个示例场景。配置入口在 `config/config.yaml`，默认使用阿里云 DashScope compatible mode：

```bash
export API_KEY_Qwen="你的 DashScope API key"
python -m examples.chat_agent.main
```

每次非 resume 运行都会创建一个 run 目录：

```text
var/runs/{run_id}/
  checkpoints/state.sqlite
  metadata.json
  trace.jsonl
```

新 run 目录名形如 `20260511_175745_123_abcd`（时间 + 毫秒 + 短随机后缀）。`metadata.json` 记录本次 run 的 `run_id`、创建时间、provider、模型名和 provider 配置快照。

恢复已有 run：

```bash
python -m examples.chat_agent.main --resume 20260511_175745_123_abcd
```

从最近 checkpoint 续跑（不提交新 query）：

```bash
python -m examples.chat_agent.main --resume 20260511_175745_123_abcd --continue-run
```

`trace.jsonl` 是 harness 自己的 append-only 事件日志，一次正常回复会写入类似事件：

```text
node_enter(reply)
llm_call(reply)
llm_response(reply)
node_exit(reply)
```

trace 只记录摘要字段（节点名、模型名、messages 数量、回答字符数、耗时），不写入完整 messages。当 graph 出现 runtime exception 时，harness 先写一条 `error`，再由 detector 生成 `failure_detected`：

```text
error(reply)
failure_detected(runtime_error)
```

后续 diagnose 和 recovery 不需要解析终端报错，直接读取稳定的 trace schema。

## Recovery Demo

```bash
python scripts/recovery_demo.py
```

预期输出：

```text
run_id: 20260512_110831_123_abcd
[step 1] plan OK
[step 2] reply FAILED: InjectedFailure: Injected failure at node 'reply' visit 1
[recovery] resuming from checkpoint
[step 2'] reply OK
DONE. Recovered from checkpoint.
```

失败注入通过 `harness.testing.inject_failure(node="reply", visit=1)` 在进程内注册，命中后访问计数会"用完"，所以 resume 续跑时第二次进入 `reply` 不会再触发。测试需要重置时调 `clear_injections()`。

## 配置和 provider

复制 `.env.example` 为 `.env`，把 `API_KEY_Qwen` 填进去。`.env` 已被 `.gitignore` 忽略。

Prompt 文件放在 `src/prompt/` 目录，示例 chat agent 当前使用：

```text
src/prompt/reply/system.md
```

如果该文件为空，会回退到代码里的默认 system prompt。

切换到本地 sglang：

```bash
export MODEL_PROVIDER=sglang
export SGLANG_API_KEY="local"
export SGLANG_BASE_URL="http://127.0.0.1:30000/v1"
python -m examples.chat_agent.main
```
