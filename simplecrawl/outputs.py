"""输出：写 json / jsonl / csv，或者把每一条交给调用方的函数/对象。"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = ["resolve_output", "write_bulk"]

PerRow = Callable[[dict[str, Any]], None]


def resolve_output(output: Any) -> tuple[PerRow | None, tuple[str, Path] | None, Callable[[], None] | None]:
    """把 output 参数解析成 (逐条回调, 批量描述, 关闭回调)。"""
    if output is None:
        return None, None, None

    if isinstance(output, (str, Path)):
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        suffix = path.suffix.lower()
        if suffix in (".jsonl", ".ndjson"):
            handle = path.open("w", encoding="utf-8")

            def write_jsonl(row: dict[str, Any]) -> None:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

            return write_jsonl, None, handle.close
        if suffix in (".json", ".csv"):
            return None, (suffix.lstrip("."), path), None
        raise ValueError(f"不支持的输出后缀 {suffix!r}，请用 .json / .jsonl / .csv")

    if callable(output):
        return output, None, None
    if hasattr(output, "write"):
        return output.write, None, None
    raise TypeError("output 需要是文件名 / 函数 / 带 write 方法的对象 / None")


def write_bulk(bulk: tuple[str, Path] | None, rows: list[dict[str, Any]]) -> None:
    if not bulk or not rows:
        return

    kind, path = bulk
    if kind == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )
