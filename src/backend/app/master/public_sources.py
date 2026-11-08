"""T-B85 fail-closed official-source preparation; NOT a completed snapshot job.

The legacy query/POST fetcher is not a documented public download source for
T-B85. Do not call it as a fallback. Only reviewed, explicitly published download
references may be added here. A successful HTML landing page is NOT a stock list.
No network, settings, credentials, DB writes or scheduler startup on import.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from app.master.sync import risk_flag

BEIJING = ZoneInfo("Asia/Shanghai")
PUBLIC_LANDING_PAGES = {
    "SH": "https://www.sse.com.cn/assortment/stock/list/share/",
    "SZ": "https://www.szse.cn/market/product/stock/list/index.html",
}
# Deliberately empty: the two HTTP200 pages have only dynamic containers, no
# verified static list or documented download reference. Do not infer API URLs.
REVIEWED_PUBLIC_DOWNLOADS: frozenset[str] = frozenset()


class PublicSourceGapError(RuntimeError):
    """Fixed nonsecret missing-source reason; never a retry instruction."""


def require_public_download(url: str) -> None:
    if url not in REVIEWED_PUBLIC_DOWNLOADS:
        raise PublicSourceGapError("official_public_download_not_verified")


def snapshot_time(day: dt.date) -> dt.datetime:
    """The project schedule is Beijing 18:00, never the bot/user timezone."""
    return dt.datetime.combine(day, dt.time(18), BEIJING)


def point_in_time_available(
    snapshot_day: dt.date,
    fetched_at: dt.datetime,
    as_of: dt.datetime,
    *,
    trading_day: bool | None,
    accepted: bool,
) -> bool:
    """Pure PIT guard for future wiring; no fabricated historical availability."""
    if fetched_at.tzinfo is None or as_of.tzinfo is None:
        raise ValueError("timezone_required")
    return (
        accepted
        and trading_day is True
        and fetched_at.astimezone(BEIJING).date() == snapshot_day
        and snapshot_time(snapshot_day) <= fetched_at <= as_of
    )


def flags(name: str, listing_status: str) -> dict[str, bool | None]:
    if not name.strip():
        raise ValueError("name_required")
    if listing_status in {"delisted", "missing_from_list"}:
        return {"f.is_st": None, "f.is_delisting_period": None}
    if listing_status not in {"listed", "delisting_period"}:
        raise ValueError("unknown_listing_status")
    derived = risk_flag(name)
    if (derived == "delisting") != (listing_status == "delisting_period"):
        raise ValueError("risk_listing_status_mismatch")
    return {
        "f.is_st": derived in {"st", "star_st", "delisting"},
        "f.is_delisting_period": listing_status == "delisting_period",
    }
