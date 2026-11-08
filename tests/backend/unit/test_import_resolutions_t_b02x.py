"""导入提示处理选项（契约 v0.2.4 #11 / §4.1“处理选项”表；后端 T-B02x ``app.importing.resolutions``）。

以 ``resolution_choices.json``（契约表快照，``test_expected_json.py`` 已与契约逐行比对）为唯一期望，
校验后端纯函数：``resolution_choices`` / ``default_resolution`` / ``is_override`` / ``validate_resolution``。
纯单元测试，不读库、不联网。后端模块不存在时 skip。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

TESTS_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(os.environ.get("AIA_BACKEND_DIR", TESTS_DIR.parent / "src" / "backend"))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
try:
    res = pytest.importorskip("app.importing.resolutions", reason="后端 T-B02x：app.importing.resolutions 未落地")
    from app.common.errors import AppError  # noqa: E402
    from app.schemas.enums import IMPORT_CODE_TABLE  # noqa: E402
except ImportError as exc:  # 后端依赖不全（如本地 tests venv 无 cryptography）
    pytest.skip(f"后端模块导入失败（T-B02x）：{exc.__class__.__name__}: {exc}", allow_module_level=True)

TABLE: dict[str, dict[str, Any]] = json.loads(Path(__file__).with_name("resolution_choices.json").read_text(encoding="utf-8"))["codes"]
ALL_CODES = sorted(s.code for s in IMPORT_CODE_TABLE)
NOT_IN_TABLE = [c for c in ALL_CODES if c not in TABLE]
OVERRIDES = [(c, o) for c, e in TABLE.items() for o in e["override"]]
NON_OVERRIDES = [(c, ch) for c, e in TABLE.items() for ch in e["choices"] if ch not in e["override"]]


def fields_of(exc: pytest.ExceptionInfo[AppError]) -> list[dict[str, str]]:
    e = exc.value
    assert e.status_code == 400 and str(e.code).endswith("VALIDATION_ERROR")
    return e.details["fields"]


def test_table_matches_contract_snapshot_exactly() -> None:
    assert set(res.RESOLUTION_TABLE) == set(TABLE)
    assert NOT_IN_TABLE, "§4.1 应有不在处理选项表中的提示码"


@pytest.mark.parametrize("code", sorted(TABLE))
def test_choices_default_and_overrides_per_code(code: str) -> None:
    e = TABLE[code]
    assert res.resolution_choices(code) == e["choices"]
    assert res.default_resolution(code) == e["choices"][0]
    assert {c for c in e["choices"] if res.is_override(code, c)} == set(e["override"])


@pytest.mark.parametrize("code", NOT_IN_TABLE[:5] + ["IMPORT_NOT_A_REAL_CODE"])
def test_codes_outside_table_have_no_choices(code: str) -> None:
    assert res.resolution_choices(code) == []
    assert res.default_resolution(code) is None
    assert not res.is_override(code, "confirm")
    with pytest.raises(AppError) as exc:
        res.validate_resolution(code, "confirm", None)
    assert fields_of(exc) == [{"field": "choice", "issue": "not_resolvable"}]


@pytest.mark.parametrize(("code", "choice"), OVERRIDES)
def test_override_requires_reason(code: str, choice: str) -> None:
    for reason in (None, "", "   \t"):
        with pytest.raises(AppError) as exc:
            res.validate_resolution(code, choice, reason)
        assert fields_of(exc) == [{"field": "reason", "issue": "required"}]
    assert res.validate_resolution(code, choice, "  核对过券商流水  ") == "核对过券商流水"


@pytest.mark.parametrize(("code", "choice"), NON_OVERRIDES)
def test_non_override_reason_optional_and_blank_normalised(code: str, choice: str) -> None:
    assert res.validate_resolution(code, choice, None) is None
    assert res.validate_resolution(code, choice, "  ") is None
    assert res.validate_resolution(code, choice, " ok ") == "ok"


def test_reason_length_bounds_after_strip() -> None:
    code, choice = OVERRIDES[0]
    assert res.REASON_MAX == 200
    assert res.validate_resolution(code, choice, "  " + "理" * 200 + "  ") == "理" * 200
    with pytest.raises(AppError) as exc:
        res.validate_resolution(code, choice, "理" * 201)
    assert fields_of(exc) == [{"field": "reason", "issue": "too_long"}]
    nc, nch = NON_OVERRIDES[0]
    with pytest.raises(AppError) as exc:
        res.validate_resolution(nc, nch, "x" * 201)
    assert fields_of(exc) == [{"field": "reason", "issue": "too_long"}]


def test_invalid_choice_reported_with_reason_issue_together() -> None:
    code = "IMPORT_DUPLICATE_IN_DB"
    with pytest.raises(AppError) as exc:
        res.validate_resolution(code, "delete_everything", "x" * 201)
    assert fields_of(exc) == [{"field": "choice", "issue": "invalid"}, {"field": "reason", "issue": "too_long"}]
    with pytest.raises(AppError) as exc:
        res.validate_resolution(code, "delete_everything", None)
    assert fields_of(exc) == [{"field": "choice", "issue": "invalid"}]


def test_spec_is_read_only() -> None:
    with pytest.raises(TypeError):
        res.RESOLUTION_TABLE["IMPORT_X"] = res.ResolutionSpec(choices=())  # type: ignore[index]
