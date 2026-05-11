# Agent Recovery Harness

一个面向 long-horizon agent 的失败恢复层：记录每个关键步骤的 checkpoint，检测长任务中的失败模式，调用诊断 agent 判断根因，并从最近的可用状态恢复执行，而不是从头重跑。

## 一句话问题

长任务 agent 跑到第 12 步挂了，今天常见的选择只有两个：从头再跑，浪费 token、时间和钱；或者直接放弃。现有 agent 框架大多只提供基础状态保存，缺少面向失败诊断和恢复策略的应用层 harness。

## 为什么重要

Long-horizon agent 正在变成主流工作流：background coding agent、research agent、workflow agent、customer support agent 都会连续执行多步任务。但任务越长，失败越常见：

- tool call 参数幻觉或 schema mismatch
- API / browser / shell 等外部工具超时
- agent 原地打转，重复执行相同步骤
- plan drift，执行轨迹偏离原始目标
- 上下文过长导致关键状态丢失

这些失败不应该默认触发“从零重跑”。更合理的做法是：保留执行轨迹，识别失败类型，选择恢复策略，然后从最近 checkpoint 继续。

## 核心方案

Agent Recovery Harness 在 agent 应用层提供四个模块：

1. **Checkpoint**
   - 按语义步骤记录 state、messages、tool results、memory 和环境快照
   - 支持 replay，并能从任意 checkpoint 恢复任务

2. **Failure Detection**
   - 检测 timeout、runtime error、tool hallucination、looping、plan drift 五类失败
   - 每类失败使用独立 detector，而不是统一用盲目 retry 处理

3. **Diagnosis**
   - 失败后调用 diagnose subagent
   - 读取 checkpoint、trace 和当前 plan
   - 输出结构化诊断：失败类型、根因、置信度、建议恢复策略

4. **Recovery Strategy**
   - 根据诊断选择恢复动作：
     - retry from checkpoint
     - fix-and-retry
     - branch alternative
     - human-in-the-loop
     - abort
   - 记录恢复效果，用于后续评估和调参

## 为什么这是 Harness，而不是 Infra

这个项目的核心不是“把状态写进数据库”，而是 long-horizon agent 的应用层设计决策：

- checkpoint 粒度怎么选：每个 tool call 都存太重，每个语义步骤又需要定义边界
- 怎么判断 agent 卡住：字面重复、语义重复、目标无进展分别如何检测
- plan drift 怎么判断：偏离原计划到底是错误，还是合理的计划修正
- recovery context 怎么注入：完整 trace 太长，summary 又可能丢关键细节
- 什么时候让人介入：不是所有失败都应该自动重试

这些问题决定了 agent 能不能可靠完成长任务，也是这个项目最有价值的部分。

## Demo 目标

计划中的最小 demo：

```bash
python failure_demo.py --task examples/complex_multi_step.json --inject-failure step=7
```

预期输出：

```text
[step 1-6] OK
[step 7] FAILED: tool_call hallucinated parameter `customer_id` (schema requires `user_id`)
[recovery] diagnosing... root_cause: schema_misuse, strategy: fix-and-retry
[step 7'] OK (with corrected param)
[step 8-12] OK
DONE. Recovered from step 7 failure. Saved 6 steps of work ($0.83, 8.2 min).
```

README 第一屏最终会放一个 30 秒 demo GIF，直接展示“失败注入 -> 诊断 -> 从 checkpoint 恢复 -> 完成任务”的完整闭环。

## 指标

项目会用 hard numbers 衡量恢复能力：

- **Recovery rate**：注入不同类型失败后，最终成功完成原任务的比例
- **Work saved**：相比从零重跑节省的 token、时间和成本
- **False positive rate**：detector 错把正常执行判成失败的比例
- **Recovery latency**：诊断和恢复本身引入的额外耗时

目标 benchmark：

- τ-bench 多步工具调用任务
- SWE-bench mini / long-horizon coding tasks
- 自定义 injected failure suite

## 计划架构

```text
agent_recovery_harness/
  checkpoints/          # checkpoint schema, persistence, replay
  detectors/            # timeout, error, tool hallucination, loop, plan drift
  diagnosis/            # diagnose subagent and structured diagnosis schema
  recovery/             # strategy router and recovery executors
  runners/              # task runner, trace recorder, failure injection
  evals/                # metrics and benchmark adapters
  examples/             # demo tasks and injected failures
```

## 8 周路线图

| Week | Milestone |
| --- | --- |
| W1-W2 | checkpoint + replay 机制，支持从任意 step 重启 |
| W3 | 实现五类 failure detector |
| W4 | diagnose subagent，输出结构化失败诊断 |
| W5 | recovery strategy router + executor |
| W6 | 在 τ-bench 多步任务上跑 baseline 对比 |
| W7 | 在 long-horizon coding tasks / SWE-bench mini 上验证 |
| W8 | README、30 秒 demo GIF、技术 blog、最终指标整理 |

## 面试 Pitch

> 我做了一个 agent 失败恢复层，在多步任务中记录 checkpoint，检测 timeout、tool hallucination、looping 和 plan drift 等失败，并用 diagnose subagent 选择恢复策略，而不是盲目从头重跑。在 τ-bench 风格任务上，目标是把失败任务恢复率从低基线显著拉高，同时平均节省大部分 retry 成本。

## 当前状态

项目处于早期设计和脚手架阶段。下一步是实现最小闭环：

1. 定义 task / step / checkpoint / trace schema
2. 实现本地 checkpoint 落盘与 replay
3. 做一个可注入 tool schema 错误的 demo runner
4. 接入第一个 detector 和 fix-and-retry recovery 策略

