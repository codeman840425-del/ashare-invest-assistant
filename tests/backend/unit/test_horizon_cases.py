"""周期分类器示例用例（docs/strategies/horizon_classifier.md §7）按 plan v0.2.3 §6.1 规则的期望（T-T01c）。

- 用测试内的**参考求值器**（只读 ``config_defaults/horizon_classifier.yaml`` 快照 = plan §6.1 代码块原文）
  按 horizon_classifier.md §3/§4 的判定顺序计算：闸门（score 0 优先，其次最小 cap）→ requires（else_score / else_cap）
  → components 取第一条命中的档位 → 数据缺失封顶 → suitable（≥ suitable_threshold，按分数降序，同分按 tie_order）。
- 用例 E（novice，次新股）：问题 37 方案 A（SH0C，classifier 1.1.0）后 short 85 → 59，suitable [short] → []；
  intraday_t 无底仓为 0（同样 ≤ 59）。与 horizon_classifier.md §7 用例 E 行一致。
- novice（或未填经验）的 intraday_t 同样封顶 59：plan §2.5.3 / §6.1 规则 IT0C（编排者默认，用户可否决，
  origin/main fce21bb/fb583bf）。若用户否决 IT0C，删去对应用例并同步快照。
- 契约 v0.2.3 #23（T-A05，7c62f59）：``SH0C``/``IT0C`` 是分类器规则 ID，只出现在 ``HorizonCap.rule_id``
  （``kind: "requires"``），**不是** reason_code。参考求值器按契约 §5 ``HorizonCap`` 结构输出 ``caps``：
  ``{horizon, cap, kind: "requires"|"data_missing", rule_id, inputs_missing}``；所有不满足的 requires（带 else_cap）
  都列出，生效值取最小；闸门（HG*）封顶不属于 HorizonCap 的两种 kind，单独放在 ``gate_caps``。
- 后端分类器（T-B30）落地后，应以同一组输入调用后端实现并比对；目前后端没有分类器，只做规则层期望。

全部为示例数值，不联网、不依赖后端。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit]

SNAP = Path(__file__).resolve().parents[1] / "api_app" / "config_defaults" / "horizon_classifier.yaml"
CFG = yaml.safe_load(SNAP.read_text(encoding="utf-8"))
RULES = CFG["rules"]
THRESHOLD = CFG["suitable_threshold"]
HORIZONS = ("intraday_t", "short", "swing", "long")
NOVICE_CAP = 59

def _cond(op: str, actual: Any, value: Any) -> bool:
    if op == "not_null":
        return actual is not None
    if actual is None:
        return False
    if op == "eq":
        return actual == value
    if op == "ne":
        return actual != value
    if op == "lt":
        return actual < value
    if op == "le":
        return actual <= value
    if op == "gt":
        return actual > value
    if op == "ge":
        return actual >= value
    if op == "in":
        return actual in value
    if op == "contains":
        return value in actual
    if op == "between":
        return value[0] <= actual <= value[1]
    raise AssertionError(f"未知 op {op}")


def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    """返回 {raw, scores, caps(HorizonCap 列表/周期), gate_caps(闸门 id/周期), suitable}。``rank_pct`` 输入直接给分位值；``f.*`` 为 None 记为缺失。"""
    raw: dict[str, int] = {}
    scores: dict[str, int] = {}
    caps: dict[str, list[dict[str, Any]]] = {}
    gate_caps: dict[str, list[str]] = {}
    for h in HORIZONS:
        spec = RULES["horizons"][h]
        zero = False
        limits: list[tuple[int, str]] = []
        hcaps: list[dict[str, Any]] = []
        gates: list[str] = []
        for g in RULES["gates"]:
            if (g["horizons"] == "all" or h in g["horizons"]) and _cond(g["op"], inputs.get(g["input"]), g.get("value")):
                if "score" in g:
                    zero = True
                else:
                    limits.append((g["cap"], g["id"]))
                    gates.append(g["id"])
        for q in spec["requires"]:
            if not _cond(q["op"], inputs.get(q["input"]), q.get("value")):
                if "else_score" in q:
                    zero = True
                else:
                    limits.append((q["else_cap"], q["id"]))
                    hcaps.append({"horizon": h, "cap": q["else_cap"], "kind": "requires", "rule_id": q["id"], "inputs_missing": []})
        total = missing = 0
        missing_keys: list[str] = []
        for c in spec["components"]:
            v = inputs.get(c["input"])
            if v is None:
                if c["input"].startswith("f."):
                    missing += max(b["pts"] for b in c["bands"])
                    missing_keys.append(c["input"])
                continue
            total += next((b["pts"] for b in c["bands"] if _cond(b["op"], v, b["value"])), 0)
        if missing >= RULES["data_missing_cap"]["missing_points_ge"]:
            limits.append((RULES["data_missing_cap"]["cap"], "data_missing"))
            hcaps.append({"horizon": h, "cap": RULES["data_missing_cap"]["cap"], "kind": "data_missing", "rule_id": None,
                          "inputs_missing": sorted(set(missing_keys))})
        raw[h] = total
        scores[h] = 0 if zero else min([total] + [c for c, _ in limits])
        caps[h] = hcaps
        gate_caps[h] = gates
    order = {h: i for i, h in enumerate(RULES["tie_order"])}
    suitable = sorted((h for h in HORIZONS if scores[h] >= THRESHOLD), key=lambda h: (-scores[h], order[h]))
    return {"raw": raw, "scores": scores, "caps": caps, "gate_caps": gate_caps, "suitable": suitable}


def rule_ids(caps: list[dict[str, Any]], kind: str = "requires") -> list[str]:
    return [c["rule_id"] for c in caps if c["kind"] == kind]


def assert_horizon_cap_shape(r: dict[str, Any]) -> None:
    """契约 §5 HorizonCap：字段齐全；requires 带 rule_id；data_missing 的 rule_id 为 null；分数 ≤ 最小 cap。"""
    for h, items in r["caps"].items():
        for c in items:
            assert set(c) == {"horizon", "cap", "kind", "rule_id", "inputs_missing"} and c["horizon"] == h
            assert c["kind"] in {"requires", "data_missing"} and 0 <= c["cap"] <= 100
            assert (c["rule_id"] is None) == (c["kind"] == "data_missing")
            assert c["inputs_missing"] == sorted(set(c["inputs_missing"]))
        if items:
            assert r["scores"][h] <= min(c["cap"] for c in items)


#: 契约 #23：规则 ID 不是 reason_code（§6.1 原因码形如 ``R_`` / 大写下划线，不含 HG*/SH0C/IT0C 这类规则 ID）
NOVICE_RULE_IDS = {"SH0C", "IT0C"}


#: 用例 B（horizon_classifier.md §7）：高振幅活跃 + 底仓 + 做T记录，advanced
CASE_B = {
    "sec.type": "stock", "sec.board": "main_board", "f.is_st": False, "f.is_delisting_period": False, "f.list_days": 2000,
    "f.intraday_amplitude_20d": 0.85, "f.amount_20d_avg": 1_200_000_000, "f.turnover_20d_avg": 0.8,
    "f.limit_up_count_20d": 2, "f.volatility_20d": 0.75, "f.ma_trend": 1, "f.momentum_60d": 1,
    "f.roe_ttm": 3, "f.profit_cagr_3y": -5, "f.dividend_continuous_years": 0, "f.fin_report_count": 30,
    "user.has_position": True, "user.has_t_trades": True, "user.avg_holding_days": 4,
    "profile.horizon_pref": ["short", "intraday_t"], "profile.effort": "high", "profile.risk_tolerance": 4,
    "profile.experience": "advanced",
}
#: 用例 E：次新（上市 40 日），无持仓无成交；偏好 [swing, short]、精力 medium、风险 3、经验 novice
CASE_E = {
    "sec.type": "stock", "sec.board": "main_board", "f.is_st": False, "f.is_delisting_period": False, "f.list_days": 40,
    "f.intraday_amplitude_20d": 0.7, "f.amount_20d_avg": 400_000_000, "f.turnover_20d_avg": 0.9,
    "f.limit_up_count_20d": 1, "f.volatility_20d": 0.85, "f.ma_trend": 1, "f.momentum_60d": None,
    "f.roe_ttm": 8, "f.profit_cagr_3y": None, "f.dividend_continuous_years": 0, "f.fin_report_count": 6,
    "user.has_position": False, "user.has_t_trades": None, "user.avg_holding_days": None,
    "profile.horizon_pref": ["swing", "short"], "profile.effort": "medium", "profile.risk_tolerance": 3,
    "profile.experience": "novice",
}


@pytest.mark.parametrize(("horizon", "rule_id"), [("short", "SH0C"), ("intraday_t", "IT0C")])
def test_snapshot_is_classifier_1_1_0_with_novice_caps(horizon, rule_id):
    assert (CFG["version_no"], CFG["classifier_version"]) == (2, "1.1.0")
    rule = next(q for q in RULES["horizons"][horizon]["requires"] if q["id"] == rule_id)
    assert (rule["input"], rule["op"], rule["value"], rule["else_cap"]) == (
        "profile.experience", "in", ["intermediate", "advanced"], NOVICE_CAP)


def test_case_b_unchanged_by_sh0c():
    r = evaluate(CASE_B)
    assert r["scores"] == {"intraday_t": 100, "short": 100, "swing": 70, "long": 20}
    assert r["suitable"] == ["short", "intraday_t", "swing"]


def test_case_e_novice_short_capped_and_not_suitable():
    """用例 E（v0.2.3）：short raw 85 被 SH0C 封顶 59；swing raw 65 被 HG6 封顶 59；suitable 为空。"""
    r = evaluate(CASE_E)
    assert r["raw"]["short"] == 85 and r["raw"]["swing"] == 65
    assert r["scores"] == {"intraday_t": 0, "short": NOVICE_CAP, "swing": 59, "long": 10}
    assert r["caps"]["short"] == [{"horizon": "short", "cap": NOVICE_CAP, "kind": "requires", "rule_id": "SH0C", "inputs_missing": []}]
    assert r["gate_caps"]["swing"] == ["HG6"] and r["caps"]["swing"] == []  # 闸门封顶不是 HorizonCap
    assert r["suitable"] == []
    assert_horizon_cap_shape(r)


def test_case_e_intraday_t_within_novice_cap():
    """用例 E 的 intraday_t（无底仓，IT0 → 0）同样不超过 59、不列为适合。"""
    r = evaluate(CASE_E)
    assert r["scores"]["intraday_t"] <= NOVICE_CAP and "intraday_t" not in r["suitable"]


def test_case_e_intraday_t_caps_contain_it0c_rule_id():
    """契约 v0.2.3 测试点（#23）：novice 夹具 intraday_t ≤ 59 且 caps 含 {horizon: intraday_t, kind: requires, rule_id: IT0C}。"""
    r = evaluate(CASE_E)
    assert {"horizon": "intraday_t", "cap": NOVICE_CAP, "kind": "requires", "rule_id": "IT0C", "inputs_missing": []} in r["caps"]["intraday_t"]
    assert r["scores"]["intraday_t"] <= NOVICE_CAP
    assert_horizon_cap_shape(r)


def test_novice_rule_ids_are_rule_ids_not_reason_codes():
    """#23：SH0C/IT0C 只作为 requires 规则的 id 出现（HorizonCap.rule_id），快照里不出现在任何 reason_code 字段。"""
    for h in ("short", "intraday_t"):
        rule = next(q for q in RULES["horizons"][h]["requires"] if q["id"] in NOVICE_RULE_IDS)
        assert "reason_code" not in rule
        assert isinstance(rule.get("reason", ""), str)  # reason 是展示文案，不是码
    blob = SNAP.read_text(encoding="utf-8")
    assert not re.search(r"reason_code[^\n]*(SH0C|IT0C)", blob)


@pytest.mark.parametrize("experience", ["intermediate", "advanced"])
def test_case_e_control_non_novice_short_suitable(experience):
    r = evaluate({**CASE_E, "profile.experience": experience})
    assert r["scores"]["short"] == 85 and r["suitable"] == ["short"]


def test_case_e_experience_unfilled_treated_as_novice():
    r = evaluate({**CASE_E, "profile.experience": None})
    assert r["scores"]["short"] == NOVICE_CAP and r["suitable"] == []


def test_novice_short_capped_even_when_otherwise_full_score():
    r = evaluate({**CASE_B, "profile.experience": "novice"})
    assert r["scores"]["short"] == NOVICE_CAP and "short" not in r["suitable"]


@pytest.mark.parametrize("experience", ["novice", None])
def test_novice_intraday_t_capped_like_short(experience):
    """IT0C：novice（或未填写）用户的 intraday_t 同样最高 59、不列为适合（用例 B 本为 100）。"""
    r = evaluate({**CASE_B, "profile.experience": experience})
    assert r["scores"]["intraday_t"] == NOVICE_CAP and rule_ids(r["caps"]["intraday_t"]) == ["IT0C"]
    assert r["scores"]["short"] == NOVICE_CAP and rule_ids(r["caps"]["short"]) == ["SH0C"]
    assert r["suitable"] == ["swing"]
    assert_horizon_cap_shape(r)
