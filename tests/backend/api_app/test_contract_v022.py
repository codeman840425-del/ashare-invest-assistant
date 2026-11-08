"""契约 v0.2.2（T-A02）新增/改动的语义：参考实现（oracle）+ 文档解析 + 后端接入点（T-T01b）。

覆盖 T-A02 报告 §6“测试”与契约 v0.2.2 变更记录：

- ``RuleRef.passed`` 为 ``boolean | null``；``rule_ids_passed`` = passed 为 true 的规则（按 rules[] 顺序，null 不列入）；
- P1b：``POST /plan-drafts`` 在信号中没有 role ∈ {entry, exit, weakening} 且 passed=true 的 RuleRef 时
  返回 ``422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL``（补“只有 veto 命中 / 只有 null”两例）；
- ``DimensionCell.rules_passed/rules_total`` 只统计 role ∈ {entry, filter, hold}；
- ``/horizon-assessments``：scores 四键都在且为 0–100 的 int（不为 null）、reasons 带 horizon/polarity、inputs_missing；
- G-01 有原因码的检查项（如一字涨停 ``LIMIT_LOCKED``）不把 state 改成 vetoed（低价股仍 veto）；
- 风险警示股票单日累计买入 50 万股上限截断（market_rules.yaml ``risk_warning.daily_buy_cap_shares``）；
- v0.2.1 起 ``/admin/*`` 对非管理员一律 404（与普通不存在路径同体、无 Allow 头）。

纯参考实现与虚构示例直接运行；需要后端实现的部分在运行时检测，未实现则 skip 并写明依赖任务。
不联网、不调用任何行情接口。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

HORIZONS = ("intraday_t", "short", "swing", "long")
P1B_ROLES = {"entry", "exit", "weakening"}
DIMCELL_ROLES = {"entry", "filter", "hold"}
G01_REASON_CHECKS = {"suspended": "SUSPENDED", "limit_locked": "LIMIT_LOCKED"}  # 示例子集，用于 oracle
SNAPSHOT_DIR = Path(__file__).resolve().parent / "config_defaults"


# ======================= 参考实现（oracle） =======================
def validate_rule_ref(ref: dict[str, Any]) -> list[str]:
    errs = []
    if ref.get("passed") not in (True, False, None):
        errs.append("passed 只能是 true/false/null")
    if "passed" not in ref:
        errs.append("缺 passed")
    if ref.get("rule_id", "").startswith(("ctx.", "plan.")):
        errs.append("rule_id 不应是表达式")
    return errs


def rule_ids_passed(refs: list[dict[str, Any]]) -> list[str]:
    return [r["rule_id"] for r in refs if r["passed"] is True]


def p1b_violated(refs: list[dict[str, Any]]) -> bool:
    """True = 应返回 422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL。"""
    return not any(r["role"] in P1B_ROLES and r["passed"] is True for r in refs)


def dimension_cell(refs: list[dict[str, Any]]) -> dict[str, Any]:
    counted = [r for r in refs if r["role"] in DIMCELL_ROLES]
    passed = [r for r in counted if r["passed"] is True]
    return {
        "rules_passed": len(passed),
        "rules_total": len(counted),
        "key_evidence_ids": [e for r in passed for e in r.get("evidence_ids", [])],
    }


def validate_horizon_assessment(obj: dict[str, Any], per_horizon: tuple[int, int] = (2, 4)) -> list[str]:
    errs = []
    scores = obj.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(HORIZONS):
        errs.append("scores 须恰好含四个周期")
    else:
        for h, v in scores.items():
            if type(v) is not int or not 0 <= v <= 100:
                errs.append(f"scores.{h} 须为 0–100 的 int（不为 null）")
    for i, r in enumerate(obj.get("reasons", [])):
        if r.get("horizon") not in HORIZONS:
            errs.append(f"reasons[{i}].horizon")
        if r.get("polarity") not in ("for", "against"):
            errs.append(f"reasons[{i}].polarity")
        if not isinstance(r.get("text"), str) or not isinstance(r.get("evidence_ids"), list):
            errs.append(f"reasons[{i}] 须是 TextWithEvidence")
    for h in HORIZONS:
        n = sum(1 for r in obj.get("reasons", []) if r.get("horizon") == h)
        if not per_horizon[0] <= n <= per_horizon[1]:
            errs.append(f"reasons 中 {h} 有 {n} 条（应 {per_horizon[0]}–{per_horizon[1]}）")
    im = obj.get("inputs_missing")
    if not isinstance(im, list) or not all(isinstance(k, str) and k.startswith("f.") for k in im):
        errs.append("inputs_missing 须是 f.* 键列表")
    if not isinstance(obj.get("classifier_version"), (str, int)):
        errs.append("缺 classifier_version")
    if not isinstance(obj.get("suitable"), list) or not set(obj["suitable"]) <= set(HORIZONS):
        errs.append("suitable 须是 horizon[]")
    return errs


def g01_outcome(checks: dict[str, bool], low_price: bool = False) -> tuple[str, list[str]]:
    """一字涨停/停牌等有原因码的检查：state 保持 entry_ok，只产出原因码；低价股仍 veto。"""
    if low_price:
        return "vetoed", []
    return "entry_ok", [code for k, code in G01_REASON_CHECKS.items() if checks.get(k)]


def risk_warning_cap(want_qty: int, bought_today: int, cap: int = 500_000) -> tuple[int, bool]:
    """草案数量截断到 cap − 当日已买；返回 (数量, 是否截断提示)。"""
    room = max(cap - bought_today, 0)
    return (min(want_qty, room), want_qty > room)


def _ref(rule_id: str, role: str, passed: bool | None, ev: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"rule_id": rule_id, "snippet_id": None, "snippet_version": None, "role": role, "dimension": "technical",
            "passed": passed, "value": None, "threshold": None, "evidence_ids": list(ev)}


# ======================= oracle 自检（正反例） =======================
def test_rule_ref_passed_three_valued():
    for v in (True, False, None):
        assert validate_rule_ref(_ref("E1", "entry", v)) == []
    assert validate_rule_ref(_ref("E1", "entry", "yes")) != []  # type: ignore[arg-type]


def test_rule_ids_passed_excludes_null_keeps_order():
    refs = [_ref("E1", "entry", True), _ref("E2", "entry", None), _ref("V1", "veto", True), _ref("E3", "entry", False)]
    assert rule_ids_passed(refs) == ["E1", "V1"]  # veto 命中 = passed true，也列入


@pytest.mark.parametrize(
    ("refs", "violated"),
    [
        pytest.param([_ref("V1", "veto", True)], True, id="only-veto-hit"),
        pytest.param([_ref("E1", "entry", None), _ref("X1", "exit", None)], True, id="only-null"),
        pytest.param([], True, id="model-refs-only"),
        pytest.param([_ref("F1", "filter", True), _ref("C1", "counter", True)], True, id="filter-counter-only"),
        pytest.param([_ref("E1", "entry", True)], False, id="entry-true"),
        pytest.param([_ref("W1", "weakening", True), _ref("E1", "entry", None)], False, id="weakening-true"),
        pytest.param([_ref("X1", "exit", True)], False, id="exit-true"),
    ],
)
def test_p1b_oracle(refs, violated):
    assert p1b_violated(refs) is violated


def test_dimension_cell_counts_only_entry_filter_hold():
    refs = [
        _ref("E1", "entry", True, ("ev1",)), _ref("F1", "filter", False), _ref("H1", "hold", None),
        _ref("V1", "veto", True, ("ev9",)), _ref("C1", "counter", True),
    ]
    cell = dimension_cell(refs)
    assert cell == {"rules_passed": 1, "rules_total": 3, "key_evidence_ids": ["ev1"]}
    assert cell["rules_passed"] <= cell["rules_total"]


def _assessment(**over: Any) -> dict[str, Any]:
    reasons = [{"horizon": h, "polarity": p, "text": "虚构理由", "evidence_ids": []} for h in HORIZONS for p in ("for", "against")]
    base = {"suitable": ["swing"], "scores": {"intraday_t": 0, "short": 59, "swing": 72, "long": 40},
            "reasons": reasons, "inputs_missing": ["f.turnover_rank_pct"], "classifier_version": "1"}
    base.update(over)
    return base


def test_horizon_assessment_oracle_accepts_valid():
    assert validate_horizon_assessment(_assessment()) == []
    assert validate_horizon_assessment(_assessment(inputs_missing=[])) == []


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"scores": {"intraday_t": None, "short": 1, "swing": 2, "long": 3}}, id="score-null"),
        pytest.param({"scores": {"short": 1, "swing": 2, "long": 3}}, id="score-missing-key"),
        pytest.param({"scores": {"intraday_t": 101, "short": 1, "swing": 2, "long": 3}}, id="score-gt-100"),
        pytest.param({"scores": {"intraday_t": 1.5, "short": 1, "swing": 2, "long": 3}}, id="score-float"),
        pytest.param({"reasons": [{"horizon": "swing", "text": "x", "evidence_ids": []}]}, id="reason-no-polarity"),
        pytest.param({"inputs_missing": None}, id="inputs-missing-null"),
        pytest.param({"inputs_missing": ["turnover"]}, id="inputs-missing-not-f"),
    ],
)
def test_horizon_assessment_oracle_rejects(bad):
    assert validate_horizon_assessment(_assessment(**bad)) != []


def test_g01_limit_locked_stays_entry_ok():
    assert g01_outcome({"limit_locked": True}) == ("entry_ok", ["LIMIT_LOCKED"])
    assert g01_outcome({"limit_locked": False}) == ("entry_ok", [])  # 打开后重评：原因消失
    assert g01_outcome({}, low_price=True)[0] == "vetoed"


@pytest.mark.parametrize(
    ("want", "bought", "out"),
    [(600_000, 0, (500_000, True)), (500_000, 0, (500_000, False)), (200_000, 400_000, (100_000, True)),
     (100, 500_000, (0, True)), (100_000, 0, (100_000, False))],
)
def test_risk_warning_cap_oracle(want, bought, out):
    assert risk_warning_cap(want, bought) == out


def test_risk_warning_cap_value_from_snapshot():
    import yaml

    data = yaml.safe_load((SNAPSHOT_DIR / "market_rules.yaml").read_text(encoding="utf-8"))
    rw = data["segments"][0]["risk_warning"]
    assert rw["daily_buy_cap_shares"] == 500_000 and rw["limit_order_only"] is True


# ======================= 文档（契约 v0.2.2） =======================
@pytest.fixture(scope="module")
def contract(docs_dir: Path) -> str:
    return (docs_dir / "api-contract.md").read_text(encoding="utf-8")


def _row(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.M)
    assert m, pattern
    return m.group(0)


def test_doc_rule_ref_passed_nullable(contract):
    row = _row(contract, r"^\| `RuleRef` \|.*$")
    assert "passed: boolean \\| null" in row


def test_doc_horizon_assessments_shape(contract):
    row = _row(contract, r"^\| GET \| `/horizon-assessments\?security_code=`.*$")
    assert "scores: {intraday_t: int, short: int, swing: int, long: int}" in row
    assert "不为 null" in row
    assert 'polarity: "for" \\| "against"' in row and "horizon: horizon" in row
    assert "inputs_missing: string[]" in row and "classifier_version" in row


def test_doc_p1b_rule(contract):
    row = _row(contract, r"^\| POST \| `/plan-drafts`.*$")
    assert "role ∈ {entry, exit, weakening} 且 passed = true" in row
    assert "422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL" in row


def test_doc_dimension_cell_roles(contract):
    assert re.search(r"DimensionCell\.rules_passed/rules_total.*只统计 role ∈ \{entry, filter, hold\}", contract)


def test_doc_admin_404_and_key_source(contract):
    assert "**统一为 404**" in contract
    row = _row(contract, r"^\| GET/POST/PATCH \| `/admin/llm/providers`.*$")
    assert 'api_key_source: "env"\\|"db"' in row and "422 VALIDATION_ERROR" in row


def test_doc_g01_not_vetoed(contract):
    assert re.search(r"G-01 与原因码 `LIMIT_LOCKED`.*不把 `state` 改为 `vetoed`", contract)


# ======================= 后端（运行时检测，未实现 → skip 写明依赖） =======================
@pytest.fixture
def client(make_client):
    return make_client()


def _paths(client) -> set[str]:
    return {getattr(r, "path", "") for r in client.app.routes}


def _schemas(client) -> dict[str, Any]:
    return client.app.openapi().get("components", {}).get("schemas", {})


def test_backend_rule_ref_passed_nullable(client):
    s = _schemas(client).get("RuleRef")
    if s is None:
        pytest.skip("后端尚无 RuleRef 模型：依赖 T-B42（求值器三值输出）/ T-B33（信号 rule_refs）")
    passed = s["properties"]["passed"]
    types = {t.get("type") for t in passed.get("anyOf", [passed])}
    assert types == {"boolean", "null"}


def test_backend_horizon_assessments_shape(client):
    if "/api/v1/horizon-assessments" not in _paths(client):
        pytest.skip("后端尚无 /horizon-assessments：依赖 T-B30（周期分类器 v1：四周期 scores、reasons.horizon/polarity、inputs_missing）")
    pytest.skip("接口已出现，需登录后取数：待 T-B03 鉴权夹具接入后用 validate_horizon_assessment 断言（T-B30）")


def test_backend_p1b_only_veto_and_only_null(client):
    if "/api/v1/plan-drafts" not in _paths(client):
        pytest.skip("后端尚无 POST /plan-drafts：依赖 T-B34（P1b 新判定）与 T-B33（信号/RuleRef）")
    pytest.skip("接口已出现：待 T-B03 鉴权与信号夹具就绪后补“只有 veto 命中 / 只有 null → 422”两例（T-B34）")


def test_backend_g01_limit_locked_entry_ok():
    pytest.skip("依赖 T-B33（G-01 原因码落点）；端到端用例“一字涨停 → entry_ok + LIMIT_LOCKED，打开后自动重评”归 T-T17")


def test_backend_risk_warning_cap(backend):
    import importlib

    try:
        mod = importlib.import_module("app.market_rules")
    except ImportError:
        mod = None
    if mod is None or not any(n for n in dir(mod) if "cap" in n.lower() or "risk_warning" in n.lower()):
        pytest.skip("后端 app.market_rules 尚无风险警示 50 万股上限：依赖 T-B36；边界值单测归 T-T19")


def test_backend_llm_api_key_source():
    pytest.skip("依赖 T-B25（/admin/llm/providers 的 api_key_source、PATCH api_key → 422）与 T-B03（管理员登录夹具）")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/llm/providers"),
        ("PATCH", "/api/v1/admin/llm/providers"),
        ("POST", "/api/v1/admin/llm/test"),
        ("GET", "/api/v1/admin/users"),
        ("DELETE", "/api/v1/admin/no-such-sub-path"),
    ],
)
def test_admin_paths_404_for_anonymous(client, method, path):
    """v0.2.1：未登录访问 /admin/* 一律 404，与普通不存在路径同体、无 Allow 头，先于 CSRF/405/422。"""
    ref = client.request(method, "/api/v1/no-such-path-for-ref")
    resp = client.request(method, path, json={"api_key": "FAKE-NOT-A-REAL-VALUE"})
    assert resp.status_code == 404, f"{method} {path} → {resp.status_code}（依赖 T-B03：/admin 未登录 → 404）"
    assert "allow" not in {k.lower() for k in resp.headers}
    err, ref_err = resp.json()["error"], ref.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert {k: v for k, v in err.items() if k != "request_id"} == {k: v for k, v in ref_err.items() if k != "request_id"}
    assert "FAKE-NOT-A-REAL-VALUE" not in resp.text
