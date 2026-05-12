from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# Run 运行上下文
@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    checkpoints_dir: Path
    trace_path: Path
    metadata_path: Path

    # 创建新的 run 目录并写入 metadata
    @classmethod
    def create(cls, run_id: str, run_root: Path, *, metadata: dict[str, Any]) -> "RunContext":
        run_ctx = cls.from_paths(run_id, run_root)
        if run_ctx.run_dir.exists():
            raise FileExistsError(f"Run already exists: {run_ctx.run_dir}")

        run_ctx.checkpoints_dir.mkdir(parents=True)
        run_ctx.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return run_ctx

    # 加载已经存在的 run 目录
    @classmethod
    def resume(cls, run_id: str, run_root: Path) -> "RunContext":
        run_ctx = cls.from_paths(run_id, run_root)
        if not run_ctx.run_dir.exists():
            raise FileNotFoundError(f"Run does not exist: {run_ctx.run_dir}")
        if not run_ctx.metadata_path.exists():
            raise FileNotFoundError(f"Run metadata does not exist: {run_ctx.metadata_path}")
        return run_ctx

    # 根据 run_id 和 run_root 计算 run 相关路径
    @classmethod
    def from_paths(cls, run_id: str, run_root: Path) -> "RunContext":
        run_dir = run_root / run_id
        checkpoints_dir = run_dir / "checkpoints"
        return cls(
            run_id=run_id,
            run_dir=run_dir,
            checkpoints_dir=checkpoints_dir,
            trace_path=run_dir / "trace.jsonl",
            metadata_path=run_dir / "metadata.json",
        )


# 生成基于当前时间的 run_id
def generate_run_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    suffix = uuid.uuid4().hex[:4]
    return f"{timestamp}_{suffix}"
