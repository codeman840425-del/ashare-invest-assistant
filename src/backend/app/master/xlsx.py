"""只读最小 xlsx 解析（标准库 zipfile + ElementTree），用于深交所报表（T-B52）。

只取第一个工作表的单元格文本：共享字符串、内联字符串与数值原文；不解析样式与公式。
不引入 openpyxl（后端镜像没有该依赖）。
"""

from __future__ import annotations

import io
import re
import zipfile

# 只解析交易所返回的 xlsx 内部 XML；ElementTree 不解析外部实体
from xml.etree import ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL = re.compile(r"^([A-Z]+)")
#: 防御：单个 XML 部件解压后的上限
_MAX_PART = 64 * 1024 * 1024


class XlsxError(ValueError):
    pass


def _col_index(ref: str) -> int:
    m = _COL.match(ref)
    if not m:
        raise XlsxError("单元格引用无法识别")
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.file_size > _MAX_PART:
        raise XlsxError("xlsx 部件过大")
    return z.read(name)


def read_rows(data: bytes) -> list[list[str]]:
    """返回第一个工作表的全部行（每行为单元格文本列表，空单元格为 ``""``）。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("不是 xlsx 文件") from exc
    with z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(_read(z, "xl/sharedStrings.xml"))  # noqa: S314
            shared = [
                "".join(t.text or "" for t in si.iter(_NS + "t")) for si in root.iter(_NS + "si")
            ]
        sheets = sorted(
            (n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
            key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[1])),
        )
        if not sheets:
            raise XlsxError("xlsx 没有工作表")
        root = ET.fromstring(_read(z, sheets[0]))  # noqa: S314
    rows: list[list[str]] = []
    for row in root.iter(_NS + "row"):
        cells: dict[int, str] = {}
        for pos, c in enumerate(row.iter(_NS + "c")):
            ref = c.get("r")
            idx = _col_index(ref) if ref else pos
            kind = c.get("t")
            v = c.find(_NS + "v")
            if kind == "s":
                if v is None or v.text is None:
                    text = ""
                else:
                    try:
                        text = shared[int(v.text)]
                    except (ValueError, IndexError) as exc:
                        raise XlsxError("共享字符串索引越界") from exc
            elif kind == "inlineStr":
                node = c.find(_NS + "is")
                text = "" if node is None else "".join(t.text or "" for t in node.iter(_NS + "t"))
            else:
                text = "" if v is None or v.text is None else v.text
            cells[idx] = text
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return rows
