# ruff: noqa: S101
"""T-T70b：替代 selfchecks/test_tb110_gate_purge::test_migration_heads_single_0030。

原例写死 heads == ["0030"]，而 be/T-B127 已有 0031/0032。硬规则只改 tests/，
故在 tests 下以动态口径重写：单头，且迁移链连续（不写死编号）。
用例改名为 test_migration_heads_single_and_chain_continuous。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]


def _script() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    return ScriptDirectory.from_config(cfg)


def _assert_single_head_continuous_chain(script: ScriptDirectory) -> None:
    heads = script.get_heads()
    assert len(heads) == 1, f"期望单头，实际 {heads}"
    head = heads[0]
    revisions = {rev.revision: rev for rev in script.walk_revisions()}
    assert revisions, "迁移链为空"
    bases: list[str] = []
    downs: list[object] = []
    for rev in revisions.values():
        down = rev.down_revision
        if down is None:
            bases.append(rev.revision)
            continue
        # 无分叉、无合并：down_revision 必须是单个已存在的上一 revision
        assert isinstance(down, str), f"{rev.revision} 的 down_revision 不是单值：{down!r}"
        assert down in revisions, f"{rev.revision} 的 down_revision={down} 不在迁移链中"
        downs.append(down)
    assert len(bases) == 1, f"期望唯一 base，实际 {bases}"
    shared = {k: v for k, v in Counter(downs).items() if v > 1}
    assert not shared, f"分叉：多个 revision 指向同一 down_revision {shared}"
    children = {
        rev.down_revision: rev.revision
        for rev in revisions.values()
        if isinstance(rev.down_revision, str)
    }
    cursor = bases[0]
    seen = [cursor]
    while cursor in children:
        cursor = children[cursor]
        seen.append(cursor)
    assert cursor == head, f"从 base 出发到达 {cursor}，不是 head {head}"
    assert set(seen) == set(revisions), "存在无法从 base 沿唯一链到达 head 的 revision"


def test_migration_heads_single_and_chain_continuous() -> None:
    """单头且迁移链连续：动态取 ScriptDirectory，不写死编号。"""
    _assert_single_head_continuous_chain(_script())
