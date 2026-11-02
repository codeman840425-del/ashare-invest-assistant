"""导入文本的纯函数工具（plan §3.5A-1，T-B46）：全角转半角、数字解析、按显示宽度切分列。

- 显示宽度：东亚宽字符（W/F）算 2 列，其余算 1 列。GBK 定宽文件按字节对齐，汉字 2 字节 =
  2 列，与按显示宽度计算的列起点一致；UTF-8 文件同样按显示宽度比较（与编码无关）。
- 切分：值内部最多 1 个空格（“科创 甲”），相邻列之间至少 2 个空格。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

_FW: Final = {cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)} | {0x3000: 0x20}
_TOKEN_RE: Final = re.compile(r"\S+(?: \S+)*")
_NUMBER_RE: Final = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_GROUPED_RE: Final = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?$")


def to_halfwidth(value: str) -> str:
    """全角 ASCII 与全角空格转半角（plan §3.5A-1：数字先全角转半角、去千分位）。"""
    return value.translate(_FW)


def parse_decimal(value: str) -> Decimal:
    """解析数字：全角转半角、去千分位逗号；不是有效数字抛 ``ValueError``。"""
    s = to_halfwidth(value).strip()
    if _GROUPED_RE.match(s):
        s = s.replace(",", "")
    if not _NUMBER_RE.match(s):
        raise ValueError(value)
    try:
        return Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - 正则已挡住
        raise ValueError(value) from exc


def display_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in value)


@dataclass(frozen=True, slots=True)
class Token:
    col: int  # 显示列起点（0 起）
    text: str
    start: int = 0  # 字符下标


def tokenize(line: str) -> list[Token]:
    """按“至少 2 个空白”切分，返回每个值的显示列起点与文本。制表符按 2 个空格处理。"""
    line = line.replace("\t", "  ")
    return [
        Token(display_width(line[: m.start()]), m.group(), m.start())
        for m in _TOKEN_RE.finditer(line)
    ]


def strip_ws(value: str) -> str:
    """去掉全部空白（名称比较用：契约 §4.1 #35，内部空格不算不同）。"""
    return "".join(to_halfwidth(value).split())


def fmt_decimal(value: Decimal, places: int) -> str:
    q = Decimal(1).scaleb(-places)
    return str(value.quantize(q))


def fmt_qty(value: Decimal) -> str:
    """数量：整数时不带小数（``"77300"``），否则去掉末尾 0。"""
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")
