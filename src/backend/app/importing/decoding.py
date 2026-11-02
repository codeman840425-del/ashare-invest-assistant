"""导入文件解码（plan §3.5A-1 文件级第 2 步，T-B46）。

先按字节切行（``\\r\\n`` / ``\\r`` / ``\\n``；GBK/GB18030 的尾字节不会是 0x0A/0x0D，所以先切行再
逐行解码是安全的），再逐行尝试候选编码：

1. 有 UTF-8 BOM → ``utf-8-sig``；
2. 除末行外都能按 UTF-8 解码且含非 ASCII → ``utf-8``；
3. 否则 ``gbk``，``gbk`` 解不了但 ``gb18030`` 能解 → ``gb18030``；
4. 都不行（解不了的行超过 10%，或解出来的非 ASCII 字符大多不是常用汉字/标点）
   → ``IMPORT_ENCODING_UNDETECTED``。

单行解码失败是行级 ``IMPORT_ROW_DECODE_ERROR``（末行不完整的多字节字符也归此码），不拒绝整文件。
置信度 = 常用汉字占非 ASCII 字符的比例 × min(1, 常用汉字数 / 20)；低于 0.8 报
``IMPORT_ENCODING_LOW_CONFIDENCE``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

SUPPORTED_ENCODINGS: Final = ("utf-8", "utf-8-sig", "gbk", "gb18030")
#: ``encoding_override`` 接受的写法 → 规范名
ENCODING_ALIASES: Final = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "gbk": "gbk",
    "gb2312": "gbk",
    "cp936": "gbk",
    "gb18030": "gb18030",
}
LOW_CONFIDENCE: Final = 0.8
_LINE_RE: Final = re.compile(rb"\r\n|\r|\n")
_BOM: Final = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class RawLine:
    row_no: int  # 物理行号，1 起
    data: bytes
    has_newline: bool


@dataclass(slots=True)
class DecodedLine:
    row_no: int
    text: str | None  # None = 本行无法解码
    has_newline: bool
    data: bytes


@dataclass(slots=True)
class Decoded:
    encoding: str | None
    confidence: float | None
    lines: list[DecodedLine]


def normalize_encoding(name: str) -> str | None:
    return ENCODING_ALIASES.get(name.strip().lower())


def split_lines(data: bytes) -> list[RawLine]:
    if data.startswith(_BOM):
        data = data[len(_BOM) :]
    out: list[RawLine] = []
    pos = 0
    n = 1
    for m in _LINE_RE.finditer(data):
        out.append(RawLine(n, data[pos : m.start()], True))
        pos = m.end()
        n += 1
    if pos < len(data):
        out.append(RawLine(n, data[pos:], False))
    return out


def _try(line: bytes, enc: str) -> str | None:
    try:
        return line.decode("utf-8" if enc == "utf-8-sig" else enc)
    except UnicodeDecodeError:
        return None


def _plausible(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x3000 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
    )


def _common_cjk(ch: str) -> bool:
    return 0x4E00 <= ord(ch) <= 0x9FFF


def _decode_all(raw: list[RawLine], enc: str) -> list[DecodedLine]:
    return [DecodedLine(r.row_no, _try(r.data, enc), r.has_newline, r.data) for r in raw]


def _failures(lines: list[DecodedLine]) -> int:
    """解码失败的行数；多行文件的末行（文件可能被截断）不计。"""
    body = lines[:-1] if len(lines) > 1 else lines
    return sum(1 for d in body if d.text is None)


def _confidence(lines: list[DecodedLine]) -> tuple[float, float]:
    """(置信度, 合理字符占比)。"""
    non_ascii = [ch for d in lines if d.text for ch in d.text if ord(ch) > 0x7F]
    if not non_ascii:
        return 1.0, 1.0
    plausible = sum(1 for ch in non_ascii if _plausible(ch)) / len(non_ascii)
    common = sum(1 for ch in non_ascii if _common_cjk(ch))
    ratio = common / len(non_ascii)
    return round(ratio * min(1.0, common / 20), 4), plausible


def decode(data: bytes, override: str | None = None) -> Decoded:
    """检测编码并逐行解码；``override`` 是用户在预览页手选的编码（已规范化）。"""
    raw = split_lines(data)
    if override is not None:
        return Decoded(override, 1.0, _decode_all(raw, override))
    if data.startswith(_BOM):
        return Decoded("utf-8-sig", 1.0, _decode_all(raw, "utf-8-sig"))
    utf8 = _decode_all(raw, "utf-8")
    if not any(b > 0x7F for b in data):
        return Decoded("utf-8", 1.0, utf8)
    if _failures(utf8) == 0:
        conf, plausible = _confidence(utf8)
        if plausible >= 0.5:
            return Decoded("utf-8", conf, utf8)
    gbk = _decode_all(raw, "gbk")
    gb18030 = _decode_all(raw, "gb18030")
    bad_gbk = sum(d.text is None for d in gbk)
    bad_gb18030 = sum(d.text is None for d in gb18030)
    enc, lines = ("gbk", gbk) if bad_gbk <= bad_gb18030 else ("gb18030", gb18030)
    if _failures(lines) > len(raw) * 0.1:
        return Decoded(
            None, None, [DecodedLine(r.row_no, None, r.has_newline, r.data) for r in raw]
        )
    conf, plausible = _confidence(lines)
    if plausible < 0.5:
        return Decoded(
            None, None, [DecodedLine(r.row_no, None, r.has_newline, r.data) for r in raw]
        )
    return Decoded(enc, conf, lines)
