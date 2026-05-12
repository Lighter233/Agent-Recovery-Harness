from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from harness import traced_node
from harness.llm.client import ChatMessage, LLMClient


# 示例 chat agent 的 graph state
class ReplyState(TypedDict, total=False):
    query: str
    plan: str
    history: list[ChatMessage]
    answer: str


# 构造 chat agent 的未 compile StateGraph，交给 Harness 接管 checkpointer
def build_chat_graph(client: LLMClient) -> StateGraph:

    # 生成本轮 query 的占位 plan
    @traced_node("plan")
    def plan(state: ReplyState) -> ReplyState:
        query = state["query"]
        return {"query": query, "plan": f"reply to: {query}"}

    # 调用 LLM 生成回答，并把本轮问答追加到 history
    @traced_node("reply")
    def reply(state: ReplyState) -> ReplyState:
        history = state.get("history", [])
        query = state["query"]
        answer = client.chat(query, history=history)
        return {
            "query": query,
            "history": [
                *history,
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ],
            "answer": answer,
        }

    graph = StateGraph(ReplyState)
    graph.add_node("plan", plan)
    graph.add_node("reply", reply)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "reply")
    graph.add_edge("reply", END)
    return graph
