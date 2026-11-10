"""Official-card universe normalization for v1 runtime (T-B119 / T-A83 / T-R43).

Card ``universe.boards`` uses the fixture/card key ``main`` (plan 2.5.14 T-R15 §4:
``board: main|chinext|star|bse``). Persist looks up ``securities.board`` with the
market-rules key ``main_board`` (same alias as ``lots.normalize_board``). Without
the alias, a main-board holding is misread as ``outside_universe``.

When ``screen`` is null, v1 does not scan the full market (T-A83 ④, S-01 card
header, ``screen.py``). The official pool literal ``全市场（持仓 ∪ 自选优先）`` is
rewritten to ``持仓 ∪ 自选``; narrative ``exclude`` (ST / halt / F2, already handled
by G-01/F2) is dropped so membership only sees ``boards`` / ``pool`` /
``security_types``; missing ``security_types`` defaults to ``["stock"]``. The raw
official pool literal remains rejected if it is passed to ``screen_membership``
without this rewrite.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.market_rules.lots import normalize_board

_OFFICIAL_V1_POOL = "全市场（持仓 ∪ 自选优先）"
_V1_HOLDINGS_WATCH = "持仓 ∪ 自选"
_DEFAULT_SECURITY_TYPES = ("stock",)


def normalize_boards(boards: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy ``main`` ↔ ``main_board`` so card keys and ``master.board`` agree."""
    flags = dict(boards or {})
    if "main_board" not in flags and "main" in flags:
        flags["main_board"] = flags["main"]
    elif "main" not in flags and "main_board" in flags:
        flags["main"] = flags["main_board"]
    return flags


def board_in_universe(boards: Mapping[str, Any] | None, board: str | None) -> bool:
    """True when the master (or card) board key is admitted."""
    flags = normalize_boards(boards)
    if board is not None and bool(flags.get(board, False)):
        return True
    return bool(flags.get(normalize_board(board), False))


def normalize_universe(
    universe: Mapping[str, Any] | None,
    *,
    screen: Any = None,  # noqa: ANN401
) -> dict[str, Any] | None:
    """Return a runtime universe; ``None`` and non-mappings are left unchanged."""
    if universe is None:
        return None
    out: dict[str, Any] = dict(universe)
    raw_boards = out.get("boards")
    if isinstance(raw_boards, Mapping):
        out["boards"] = normalize_boards(raw_boards)
    if screen is not None:
        return out
    if out.get("pool") == _OFFICIAL_V1_POOL:
        out["pool"] = _V1_HOLDINGS_WATCH
    out.pop("exclude", None)
    if "security_types" not in out or out.get("security_types") is None:
        out["security_types"] = list(_DEFAULT_SECURITY_TYPES)
    return out
