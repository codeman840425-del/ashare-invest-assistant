"""T004 导入验收用例（53 条）的可执行骨架（T-T01）。

- `import_cases.json` 只记录用例 ID / 优先级 / 夹具文件名，用例正文以
  team/reports/T004-import-cases.md 为准（本任务不改动该文档与夹具结构）。
- 映射本身的一致性现在就能验证（会 pass）。
- 每条用例一个参数化占位：解析器（plan §6 `app.importing`，T-B 系列）落地前 **skip**；
  落地后由实现者把对应用例替换为真实断言（删掉 skip 分支即可）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = TESTS_DIR.parent
FMT_A = TESTS_DIR / "fixtures" / "broker_statements" / "fmt_a"
MAPPING = json.loads((Path(__file__).with_name("import_cases.json")).read_text(encoding="utf-8"))
CASES = MAPPING["cases"]
META_FILES = {e["file"] for e in json.loads((FMT_A / "meta.json").read_text(encoding="utf-8"))["files"]}

EXPECTED_GROUPS = {"ENC": 11, "FW": 8, "NUM": 10, "SIDE": 5, "DUP": 8, "POS": 5, "PRIV": 4, "BATCH": 2}

# 解析器入口（plan §6：src/backend/app/importing/registry.py + parsers/）。
PARSER_MODULE = "app.importing.registry"


def _parser_available() -> bool:
    backend = str(REPO_ROOT / "src" / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    try:
        return importlib.util.find_spec(PARSER_MODULE) is not None
    except ModuleNotFoundError:
        return False


PARSER_AVAILABLE = _parser_available()


@pytest.mark.unit
def test_mapping_has_53_unique_cases() -> None:
    ids = [c["id"] for c in CASES]
    assert MAPPING["count"] == len(ids) == 53
    assert len(set(ids)) == 53
    counts: dict[str, int] = {}
    for c in CASES:
        counts[c["group"]] = counts.get(c["group"], 0) + 1
    assert counts == EXPECTED_GROUPS


@pytest.mark.unit
def test_mapping_references_only_registered_fixtures() -> None:
    referenced = {f for c in CASES for f in c["fixtures"]}
    assert referenced <= META_FILES, sorted(referenced - META_FILES)
    assert all(c["priority"] in {"P0", "P1", "P2"} for c in CASES)


@pytest.mark.import_case
@pytest.mark.pending_impl
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_import_case(case: dict) -> None:
    if not PARSER_AVAILABLE:
        pytest.skip(f"{case['id']}：等待解析器 {PARSER_MODULE} 落地（T-B 系列）")
    pytest.fail(f"{case['id']}：解析器已存在，请把本占位替换为真实断言")  # pragma: no cover
