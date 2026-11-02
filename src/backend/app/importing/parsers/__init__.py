"""导入解析器登记（T-B46）。

注意：不提供 ``app.importing.registry`` 模块——测试骨架用它是否存在来切换用例状态，
由测试角色在编写运行时构造器时接入（见 reports/T-B46.md）。
"""

from __future__ import annotations

from typing import Final

from app.importing.parsers.tdx import POSITIONS, TRADES, ParserSpec

PARSERS: Final[dict[str, ParserSpec]] = {TRADES.parser_id: TRADES, POSITIONS.parser_id: POSITIONS}
#: 旧名（plan §3.5A：fmt_a_* 保留为别名）
ALIASES: Final[dict[str, str]] = {
    "fmt_a_trades_v1": TRADES.parser_id,
    "fmt_a_positions_v1": POSITIONS.parser_id,
}
DEFAULT_FOR_KIND: Final[dict[str, str]] = {
    "trades": TRADES.parser_id,
    "positions": POSITIONS.parser_id,
}


def resolve_parser_id(parser_id: str) -> str | None:
    pid = ALIASES.get(parser_id, parser_id)
    return pid if pid in PARSERS else None
