"""检查上游是否有新提交，并评估与本仓库的冲突面。

用法：
    python scripts/check_upstream.py              # 以最后一次同步记录为起点
    python scripts/check_upstream.py v2.2.8       # 显式指定起点

只读：不改工作区、不合并。输出每个上游提交的摘要，以及它与本仓库
改动过的文件有多少重叠，用于判断同步成本。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UPSTREAM = "upstream/master"

# 上游频繁改动、且本仓库也重写过的文件：重叠越多，手工移植成本越高。
HIGH_CONFLICT_FILES = {
    "roles/front_desk.py",
    "core/conversation_ledger.py",
    "core/angel_heart_status.py",
    "core/utils/context_utils.py",
    "main.py",
}


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


def main() -> int:
    explicit = sys.argv[1] if len(sys.argv) > 1 else None
    base = resolve_base(explicit)

    commits = git("log", "--oneline", f"{base}..{UPSTREAM}").splitlines()
    if not commits:
        print(f"上游无新提交（起点 {base}）")
        return 0

    print(f"上游新增 {len(commits)} 个提交（{base}..{UPSTREAM}）\n")
    for line in commits:
        print(f"  {line}")

    changed = set(git("diff", "--name-only", f"{base}..{UPSTREAM}").splitlines())
    stat = git("diff", "--stat", f"{base}..{UPSTREAM}").splitlines()
    if stat:
        print(f"\n上游改动 {len(changed)} 个文件，最后一行统计：")
        print(f"  {stat[-1].strip()}")

    risky = sorted(changed & HIGH_CONFLICT_FILES)
    if risky:
        print("\n⚠ 高冲突面（上游与本仓库都改过，需手工移植）：")
        for path in risky:
            print(f"  - {path}")
    else:
        print("\n✓ 无高冲突面文件，可直接评估 cherry-pick")

    tests = sorted(p for p in changed if p.startswith("tests/"))
    if tests:
        print("\n上游新增/修改的测试（移植时一并带走）：")
        for path in tests:
            print(f"  - {path}")

    print("\n下一步：读 CHANGELOG 差异判断价值 → 按 docs/upstream_sync.md 手工移植")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
