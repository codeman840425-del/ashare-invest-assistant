"""golden 用例执行器（T-T01）：cases/**/*.json → 被测函数 → 逐字段比对 expected。

当前没有业务实现，只有 `_harness_selftest` 用例会真正执行（用本文件内的确定性假实现验证执行器本身）；
其他 subject 在对应模块落地前 skip。用例格式见 README.md。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

pytest.importorskip("hypothesis", reason="optional golden property-test dependency")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from golden_compare import diff_fields  # noqa: E402

REPO_ROOT = HERE.parents[2]
CASES = sorted((HERE / "cases").rglob("*.json"))

# subject → "模块:函数"（模块落地后在这里登记即可，无需改执行器）
SUBJECTS: dict[str, str] = {
    "strategy_eval": "app.strategy.evaluator:evaluate",
    "advice_build": "app.advice:build_suggestion",
}


def _selftest_impl(inp: dict[str, Any]) -> dict[str, Any]:
    """确定性假实现：收盘价站上 MA20 → watch，否则 hold。仅用于验证执行器。"""
    snap = inp["snapshot"]
    above = snap["close"] > snap["ma20"]
    return {
        "action": "watch" if above else "hold",
        "score": 60 if above else 40,
        "reasons": [{"code": "close_above_ma20" if above else "close_below_ma20"}],
    }


def _resolve(subject: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if subject == "_harness_selftest":
        return _selftest_impl
    target = SUBJECTS.get(subject)
    if target is None:
        return None
    backend = str(REPO_ROOT / "src" / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    mod_name, func = target.split(":")
    try:
        if importlib.util.find_spec(mod_name) is None:
            return None
    except ModuleNotFoundError:
        return None
    return getattr(importlib.import_module(mod_name), func, None)


def test_cases_directory_not_empty() -> None:
    assert CASES, "golden/cases 下至少应有示例用例"


@pytest.mark.golden
@pytest.mark.parametrize("case_path", CASES, ids=[str(p.relative_to(HERE / "cases")) for p in CASES])
def test_golden_case(case_path: Path) -> None:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    for key in ("id", "subject", "input", "expected"):
        assert key in case, f"{case_path.name} 缺少字段 {key}"
    impl = _resolve(case["subject"])
    if impl is None:
        pytest.skip(f"{case['id']}：subject={case['subject']} 的实现尚未落地")
    actual = impl(case["input"])
    diffs = diff_fields(case["expected"], actual, "expected")
    assert not diffs, f"{case['id']} 不一致字段：{diffs}"


@pytest.mark.golden
def test_comparator_reports_field_paths() -> None:
    exp = {"action": "watch", "reasons": [{"code": "a"}, {"code": "b"}], "price": "10.25"}
    act = {"action": "watch", "reasons": [{"code": "a"}, {"code": "c"}], "price": 10.25, "extra": 1}
    assert diff_fields(exp, act) == ["$.extra（多出）", "$.price", "$.reasons[1].code"]
    assert diff_fields(exp, exp) == []


# hypothesis 属性测试示例：任意 JSON 值与自身比较都没有差异
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=4), children, max_size=4),
    max_leaves=20,
)


@pytest.mark.golden
@settings(max_examples=200, deadline=None)
@given(_json)
def test_comparator_identity_property(value: object) -> None:
    assert diff_fields(value, value) == []
