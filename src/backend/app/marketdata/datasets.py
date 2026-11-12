"""Security dataset applicability views; public identity, no unscoped vendor data.

The four legacy market tables do not identify the fetching licence. They cannot
prove ownership and are deliberately not a source for these per-user responses.
No owned provider/cache has been wired for applicable datasets yet; expose that
source gap without fabricating a fetch, a pending job, a timestamp or market rows.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import Connection

from app.marketdata.security_types import GAP_KEYS, dataset_gap
from app.master.profile import profile

Dataset = Literal["financials", "fund-flows", "factors", "announcements"]
ANNOUNCEMENT_DISCLAIMER = "公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。"


def empty_dataset(
    conn: Connection, owner: uuid.UUID, code: str, dataset: Dataset
) -> dict[str, Any]:
    """Check canonical public identity and choose the actual applicability state."""
    security = profile(conn, owner, code)
    gap = dataset_gap(security["type"], dataset)
    if gap is not None:
        message = (
            "该证券类型不适用此数据集"
            if gap["reason"] == "not_applicable"
            else "该证券类型无此数据源"
        )
    else:
        # profile checks only the caller's licence status, never another owner's.
        unavailable = any(item["reason"] == "data_licence_unavailable" for item in security["gaps"])
        gap = {
            "key": GAP_KEYS[dataset],
            "reason": "data_licence_unavailable" if unavailable else "no_source",
        }
        message = "本人数据证书不可用" if unavailable else "本人证书下此数据集尚无可用来源"
    content: dict[str, Any] = {
        "security_code": security["security_code"],
        "name": security["name"],
        "items": [],
        "sources": [],
        "data_status": "unavailable",
        "data_as_of": None,
        "gaps": [{**gap, "message": message}],
    }
    if dataset == "factors":
        # No applicable, owned factor set exists for this empty unavailable view.
        # A real set must supply its actual string version together with its items.
        content.update(
            trade_date=None, factor_set_version=None, counts={"total": 0, "by_category": {}}
        )
    elif dataset == "announcements":
        content.update(next_cursor=None, disclaimer=ANNOUNCEMENT_DISCLAIMER)
    return content
