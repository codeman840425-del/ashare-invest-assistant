"""快照校验：整份拒收（plan 4.6.4，T-B52）。

每份列表单独判定，命中任一条即整份拒收（``parse_status='rejected'``），沿用上一份成功快照：

- ``empty``：0 行；
- ``drop_pct``：行数比该来源上一份成功快照少 ``master.reject_drop_pct``（%）以上（首次导入
  不查，没有上一份快照时也不查）；
- ``key_missing``：关键字段任一缺失率超过 ``master.reject_key_missing_pct``（%）；
- ``parse_error``：解析失败（由调用方在解析阶段判定）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

from app.config_files import SecuritiesMaster
from app.master.sources import CodeMapRow, DelistRow, ListRow, RenameRow, Row

RejectReason = Literal["empty", "drop_pct", "key_missing", "parse_error"]

#: 每类行的关键字段（plan：代码、简称、上市日期；终止上市名单还要终止日期）
KEY_FIELDS: Final[dict[type, tuple[str, ...]]] = {
    ListRow: ("code", "name", "list_date"),
    DelistRow: ("code", "name", "delist_date"),
    RenameRow: ("changed_on", "code", "after"),
    CodeMapRow: ("old_code", "new_code", "name"),
}


def missing_pct(rows: Sequence[Row]) -> float:
    """关键字段中缺失率最高的那个字段的缺失率（%）。"""
    if not rows:
        return 0.0
    worst = 0
    for f in KEY_FIELDS[type(rows[0])]:
        worst = max(worst, sum(1 for r in rows if getattr(r, f) in (None, "")))
    return 100.0 * worst / len(rows)


def validate(
    rows: Sequence[Row],
    cfg: SecuritiesMaster,
    *,
    prev_ok_count: int | None,
    check_drop: bool,
) -> RejectReason | None:
    if not rows:
        return "empty"
    if check_drop and prev_ok_count:
        drop = 100.0 * (prev_ok_count - len(rows)) / prev_ok_count
        if drop > cfg.reject_drop_pct:
            return "drop_pct"
    if missing_pct(rows) > cfg.reject_key_missing_pct:
        return "key_missing"
    return None
