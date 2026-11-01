"""解析 docs/api-contract.md 与 docs/plan.md 中的码表（CI 共用，只依赖标准库）。

契约是码表的唯一事实来源：§3 枚举、§4 错误码、§4.1 导入提示码、§6.1 原因码；
G1–G7 门禁码取自 §1 的大小写规则说明。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs" / "api-contract.md"
PLAN = REPO_ROOT / "docs" / "plan.md"

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
ENUM_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_TICK = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class ImportCodeRow:
    no: int
    code: str
    severity: str
    scope: str
    cells: tuple[str, ...]  # 整行单元格（逐行比对 plan 3.5A-1 用）

    @property
    def generator_only(self) -> bool:
        return "生成器" in self.cells[-1]


def _section(text: str, heading_re: str, *, stop_at_any: bool = False) -> list[str]:
    """返回从匹配标题开始、到下一个同级或更高级标题之前的行（``stop_at_any``：遇到任何标题即停）。"""
    lines = text.splitlines()
    pat = re.compile(heading_re)
    for i, line in enumerate(lines):
        m = re.match(r"^(#+)\s", line)
        if m and pat.search(line):
            level = len(m.group(1))
            out = []
            for nxt in lines[i + 1 :]:
                m2 = re.match(r"^(#+)\s", nxt)
                if m2 and (stop_at_any or len(m2.group(1)) <= level):
                    break
                out.append(nxt)
            return out
    raise SystemExit(f"找不到标题：{heading_re}")


def _table_rows(lines: list[str]) -> list[list[str]]:
    """Markdown 表格的数据行（去掉表头与分隔行）。"""
    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not in_table:
            in_table = True  # 表头
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _first_tick(cell: str) -> str | None:
    m = _TICK.search(cell)
    return m.group(1) if m else None


def contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def error_codes(text: str | None = None) -> dict[str, int]:
    """§4：code -> HTTP 状态码。重复的 code 会抛错。"""
    text = text or contract_text()
    out: dict[str, int] = {}
    for cells in _table_rows(_section(text, r"^## 4\. ", stop_at_any=True)):
        code = _first_tick(cells[1]) if len(cells) > 1 else None
        if not code or not cells[0].isdigit():
            continue
        if code in out:
            raise SystemExit(f"§4 错误码重复：{code}")
        out[code] = int(cells[0])
    return out


def import_codes(text: str | None = None, *, source: str = "contract") -> list[ImportCodeRow]:
    """§4.1（或 plan 3.5A-1）的导入提示码行。"""
    if source == "contract":
        lines = _section(text or contract_text(), r"^### 4\.1 ")
    else:
        lines = _section(text or PLAN.read_text(encoding="utf-8"), r"^#### 3\.5A-1 ")
    rows = []
    for cells in _table_rows(lines):
        if not cells or not cells[0].isdigit():
            continue
        code = _first_tick(cells[1])
        if not code:
            raise SystemExit(f"导入提示码表第 {cells[0]} 行没有码：{cells}")
        rows.append(ImportCodeRow(int(cells[0]), code, cells[2], cells[3], tuple(cells)))
    return rows


def reason_codes(text: str | None = None) -> list[str]:
    text = text or contract_text()
    out = []
    for cells in _table_rows(_section(text, r"^### 6\.1 ")):
        code = _first_tick(cells[0])
        if code:
            out.append(code)
    return out


def gate_codes(text: str | None = None) -> list[str]:
    text = text or contract_text()
    m = re.search(r"`G1`\s*[–-]\s*`G(\d)`", text)
    if not m:
        raise SystemExit("契约中找不到 G1–Gn 门禁码范围")
    return [f"G{i}" for i in range(1, int(m.group(1)) + 1)]


def enums(text: str | None = None) -> dict[str, list[str]]:
    """§3：枚举名 -> 取值（去掉全角括号里的说明后，取反引号记号）。"""
    text = text or contract_text()
    out: dict[str, list[str]] = {}
    for cells in _table_rows(_section(text, r"^## 3\. ")):
        name = _first_tick(cells[0])
        if not name:
            continue
        cell = cells[1]
        while True:
            stripped = re.sub(r"（[^（）]*）", "", cell)
            if stripped == cell:
                break
            cell = stripped
        out[name] = _TICK.findall(cell)
    return out
