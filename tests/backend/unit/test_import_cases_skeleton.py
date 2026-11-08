"""T004 导入验收用例（54 条 = 原 53 条 + T-T01a 新增 TC-ENC-12）的可执行骨架。

- `import_cases.json` 只记录用例 ID / 优先级 / 夹具文件名；用例说明见
  /workspace/team/reports/T004-import-cases.md（v2，码已对齐 api-contract v0.2）。
- **期望结果只从 `fmt_a/expected.json` 读取**（T-T01a 起的唯一期望来源；README §6 只是引用）。
- 映射与 expected.json 的一致性现在就能验证（会 pass）。
- 每条用例一个参数化占位：解析器（plan §6 `app.importing`，T-B 系列）落地前 **skip**；
  落地后由实现者把占位替换为真实断言（期望已作为参数传入，删掉 skip 分支即可）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = TESTS_DIR.parent
FMT_A = TESTS_DIR / "fixtures" / "broker_statements" / "fmt_a"
MAPPING = json.loads((Path(__file__).with_name("import_cases.json")).read_text(encoding="utf-8"))
CASES = MAPPING["cases"]
META_FILES = {e["file"] for e in json.loads((FMT_A / "meta.json").read_text(encoding="utf-8"))["files"]}
EXPECTED = json.loads((FMT_A / "expected.json").read_text(encoding="utf-8"))

EXPECTED_GROUPS = {"ENC": 12, "FW": 8, "NUM": 10, "SIDE": 5, "DUP": 8, "POS": 5, "PRIV": 4, "BATCH": 2}

# 解析器入口（plan §6：src/backend/app/importing/registry.py + parsers/）。
PARSER_MODULE = "app.importing.registry"
BACKEND_DIR = Path(os.environ.get("AIA_BACKEND_DIR", REPO_ROOT / "src" / "backend")).resolve()


def _parser_available() -> bool:
    backend = str(BACKEND_DIR)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    try:
        return importlib.util.find_spec(PARSER_MODULE) is not None
    except ModuleNotFoundError:
        return False


PARSER_AVAILABLE = _parser_available()


def expected_for(case: dict) -> dict:
    """用例引用的每个夹具 → expected.json.files 条目，外加引用该用例的场景。"""
    return {
        "files": {f: EXPECTED["files"][f] for f in case["fixtures"]},
        "scenarios": [s for s in EXPECTED["scenarios"] if case["id"] in s.get("cases", [])],
    }


@pytest.mark.unit
def test_mapping_has_54_unique_cases() -> None:
    ids = [c["id"] for c in CASES]
    assert MAPPING["count"] == len(ids) == 54
    assert len(set(ids)) == 54
    counts: dict[str, int] = {}
    for c in CASES:
        counts[c["group"]] = counts.get(c["group"], 0) + 1
    assert counts == EXPECTED_GROUPS


@pytest.mark.unit
def test_original_53_ids_unchanged() -> None:
    """T-T01a 只追加 TC-ENC-12，原 53 条编号与顺序不变。"""
    ids = [c["id"] for c in CASES if c["id"] != "TC-ENC-12"]
    assert len(ids) == 53
    assert ids[:11] == [f"TC-ENC-{i:02d}" for i in range(1, 12)]
    assert [c["id"] for c in CASES].index("TC-ENC-12") == 11


@pytest.mark.unit
def test_mapping_references_only_registered_fixtures() -> None:
    referenced = {f for c in CASES for f in c["fixtures"]}
    assert referenced <= META_FILES, sorted(referenced - META_FILES)
    assert all(c["priority"] in {"P0", "P1", "P2"} for c in CASES)


@pytest.mark.unit
def test_every_case_fixture_has_expected_entry() -> None:
    missing = sorted({f for c in CASES for f in c["fixtures"]} - set(EXPECTED["files"]))
    assert not missing, f"expected.json 缺少这些夹具的期望：{missing}"


@pytest.mark.unit
def test_every_expected_file_is_used_by_a_case() -> None:
    referenced = {f for c in CASES for f in c["fixtures"]}
    unused = sorted(set(EXPECTED["files"]) - referenced)
    assert not unused, f"expected.json 中这些夹具没有任何 T004 用例引用：{unused}"


@pytest.mark.unit
def test_scenario_case_ids_exist() -> None:
    ids = {c["id"] for c in CASES}
    for s in EXPECTED["scenarios"]:
        assert s["cases"] and set(s["cases"]) <= ids, s["id"]


@pytest.mark.unit
def test_cr_case_maps_to_cr_fixture() -> None:
    case = next(c for c in CASES if c["id"] == "TC-ENC-12")
    exp = expected_for(case)["files"]["trades_cr.txt"]
    assert exp["same_as"]["file"] == "trades_sample.txt"
    assert sorted(int(k) for k in exp["same_as"]["row_map"]) == [4, 5, 6, 7, 8]


@pytest.mark.import_case
@pytest.mark.pending_impl
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_import_case(case: dict) -> None:
    expected = expected_for(case)  # 无夹具的用例（如 TC-PRIV-03/04、TC-POS-05）只依赖场景或前置状态
    if not PARSER_AVAILABLE:
        pytest.skip(f"{case['id']}：等待解析器 {PARSER_MODULE} 落地（T-B 系列；期望已就绪：expected.json）")
    pytest.fail(f"{case['id']}：解析器已存在，请把本占位替换为真实断言（期望见 expected_for(case)）")  # pragma: no cover
