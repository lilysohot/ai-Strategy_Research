"""冻结修订的共享工具：**archive-first** + 归档忠实性断言。

本会话的教训（三次"先改后归档"导致归档声明不真实）之后，把顺序固化成可复用函数：

- ``archive_first(paths, before_dir)``：在**任何改动之前**调用，把将被覆盖的绑定路径复制到
  ``before_dir``，并逐条与**上一修订绑定**比对，返回带 ``matches_previous_binding`` 的记录；
- ``assert_archives_faithful(records)``：任一归档与上一绑定不符即抛错（拒绝留下假归档）。

新修订必须**先**调用 ``archive_first``，再做任何写入。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

__all__ = [
    "digest",
    "load_json",
    "merged_binding",
    "previous_binding",
    "archive_first",
    "assert_archives_faithful",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def merged_binding(freezes_dir: Path, *, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """复刻验证器语义：按修订序号合并绑定，最新修订优先。"""

    current: dict[str, str] = {}
    paths = sorted(Path(freezes_dir).glob("i0c-r*.json")) + sorted(Path(freezes_dir).glob("i1-*.json"))
    for path in paths:
        if path.stem in exclude:
            continue
        data = load_json(path)
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


def previous_binding(freezes_dir: Path, *, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    return merged_binding(freezes_dir, exclude=exclude)


def archive_first(
    paths: list[str],
    before_dir: Path,
    *,
    root: Path,
    freezes_dir: Path,
    exclude: tuple[str, ...] = (),
) -> list[dict]:
    """**任何改动之前**调用：归档 + 逐条与上一绑定校验。"""

    expected_map = previous_binding(freezes_dir, exclude=exclude)
    records: list[dict] = []
    for relative in paths:
        source = root / relative
        target = Path(before_dir) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copy2(source, target)
        expected = expected_map.get(relative)
        actual = digest(target)
        records.append(
            {
                "path": relative,
                "archived_as": str(target.relative_to(root)),
                "sha256": actual,
                "matches_previous_binding": expected is None or expected == actual,
            }
        )
    return records


def assert_archives_faithful(records: list[dict]) -> None:
    bad = [record["path"] for record in records if not record["matches_previous_binding"]]
    if bad:
        raise RuntimeError(f"归档与上一修订绑定不符（先改后归档？）：{bad}")
