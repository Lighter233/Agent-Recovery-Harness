from __future__ import annotations


# 测试和 demo 用的人造失败，由 inject_failure 显式触发
class InjectedFailure(RuntimeError):
    pass


# node 名 -> 命中所需的访问次数
_INJECTIONS: dict[str, int] = {}

# node 名 -> 已经看到的访问次数
_VISITS: dict[str, int] = {}


# 注册一次失败注入：第 visit 次进入该节点时抛 InjectedFailure
def inject_failure(*, node: str, visit: int = 1) -> None:
    if visit < 1:
        raise ValueError(f"visit must be >= 1, got {visit}")
    _INJECTIONS[node] = visit
    _VISITS.pop(node, None)


# 清空所有失败注入，主要给测试用
def clear_injections() -> None:
    _INJECTIONS.clear()
    _VISITS.clear()


# 由 @traced_node 装饰器内部调用：命中目标 visit 时抛 InjectedFailure
def _maybe_inject(node: str) -> None:
    target = _INJECTIONS.get(node)
    if target is None:
        return
    _VISITS[node] = _VISITS.get(node, 0) + 1
    if _VISITS[node] == target:
        raise InjectedFailure(f"Injected failure at node {node!r} visit {_VISITS[node]}")
