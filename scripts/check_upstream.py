"""检查上游是否有新提交，并评估与本仓库的真实冲突面。

用法：
    git fetch upstream --tags          # 本脚本不联网，先手动拉取
    python scripts/check_upstream.py    # 以最后一次同步记录为起点
    python scripts/check_upstream.py a1e1b05   # 显式指定起点

只读：不 fetch、不改工作区、不合并。冲突检测用 `git merge-tree` 在内存里
试算合并，得到的冲突文件是真实结果，不是「双方都改过」的近似名单。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UPSTREAM = "upstream/master"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout.strip()


def resolve_base(explicit: str | None) -> str:
    if explicit:
        return explicit
    # 上次同步到的上游提交记录在 docs/upstream_sync_point.txt。
    # 用记录而非 merge-base：分叉点只是历史分叉处，不等于已经同步到哪儿。
    pointer = Path(__file__).resolve().parent.parent / "docs" / "upstream_sync_point.txt"
    if pointer.is_file():
        recorded = pointer.read_text(encoding="utf-8").strip()
        if recorded:
            return recorded
    print("⚠ 未找到 docs/upstream_sync_point.txt 记录，回退到 merge-base（可能重复报告已同步的提交）")
    return git("merge-base", "HEAD", UPSTREAM)


def merge_conflicts() -> tuple[list[str], str]:
    """用 merge-tree 在内存里试算 HEAD 与上游的合并，返回真实冲突文件。

    成功时 git 输出首行是树 hash，无冲突则没有其他行；
    有冲突时每行形如 `<mode> <object> <stage>\\t<path>`，同一 path 出现 1/2/3 三阶段。
    """
    result = subprocess.run(
        ["git", "merge-tree", "--write-tree", "HEAD", UPSTREAM],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = (result.stdout or "").splitlines()
    if result.returncode == 0:
        return [], ""

    conflicts: set[str] = set()
    for line in lines[1:]:
        if "\t" in line:
            conflicts.add(line.split("\t", 1)[1])
    note = "" if conflicts else "merge-tree 非零退出但未解析出冲突文件，可能只是元数据问题"
    return sorted(conflicts), note


def main() -> int:
    explicit = sys.argv[1] if len(sys.argv) > 1 else None
    base = resolve_base(explicit)

    commits = git("log", "--oneline", f"{base}..{UPSTREAM}").splitlines()
    if not commits:
        print(f"上游无新提交（起点 {base}）")
        print("提示：本脚本不联网，若怀疑落后请先 git fetch upstream --tags")
        return 0

    print(f"上游新增 {len(commits)} 个提交（{base}..{UPSTREAM}）\n")
    for line in commits:
        print(f"  {line}")

    changed = set(git("diff", "--name-only", f"{base}..{UPSTREAM}").splitlines())
    stat = git("diff", "--stat", f"{base}..{UPSTREAM}").splitlines()
    if stat:
        print(f"\n上游改动 {len(changed)} 个文件：{stat[-1].strip()}")

    conflicts, note = merge_conflicts()
    if note:
        print(f"\n⚠ {note}")
    if conflicts:
        print(f"\n⚠ 与当前 HEAD 真实冲突 {len(conflicts)} 个文件（merge-tree 试算）：")
        for path in conflicts:
            print(f"  - {path}")
    else:
        print("\n✓ merge-tree 试算无冲突，可评估直接 cherry-pick")

    tests = sorted(p for p in changed if p.startswith("tests/"))
    if tests:
        print("\n上游新增/修改的测试（移植时一并带走）：")
        for path in tests:
            print(f"  - {path}")

    print("\n下一步：读 CHANGELOG 差异判断价值 → 按 docs/upstream_sync.md 手工移植")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
