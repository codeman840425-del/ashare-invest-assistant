"""周期分类器示例用例按 plan §6.1 ``horizon_classifier.yaml`` 规则的期望（T-T01c 建立；T-T01d 同步契约 v0.2.5 / 分类器 1.2.0）。

- 用测试内的**参考求值器**（只读 ``config_defaults/horizon_classifier.yaml`` 快照 = plan v0.2.5 §6.1 代码块原文）
  按 horizon_classifier.md §3/§4 的判定顺序计算：闸门（score 0 优先，其次最小 cap）→ requires → components 取第一条
  命中的档位 → 数据缺失封顶 → suitable（≥ suitable_threshold，按分数降序，同分按 tie_order）。
- 契约 v0.2.5（T-A06 bd33f83，用户 2026-11-02 决定）：requires 规则新增 ``mode: cap``（默认）| ``hint``。
  画像类规则 SH0/SH0B/SH0C/IT0B/IT0C 为 ``mode: hint``：输入未填写 → 跳过（不提示、不封顶）；已填写且不满足 →
  只写入 ``hints[]``（``HorizonHint {horizon, rule_id, text}``），不改分数、不进 ``caps[]``、不影响 ``suitable``。
  ``mode: cap`` 的规则不满足时进 ``caps``（``kind: "requires"``；``else_score`` 的 cap 记 0，如 IT0 无底仓）。
- 契约 §5 ``HorizonCap``：``{horizon, cap, kind: "requires"|"data_missing", rule_id, inputs_missing}``；
  闸门（HG*）封顶不属于 HorizonCap 的两种 kind，单独放在 ``gate_caps``。规则 ID 不是 reason_code（v0.2.3 #23）。
- 用例 E（novice，次新股）：1.1.0 时 short 被 SH0C 封顶 59；1.2.0 起只提示，short 85、suitable [short]。
  docs/strategies/horizon_classifier.md §7 用例 E 行仍是 1.1.0 口径（研究员按 T-A06 §6 更新），本文件以 plan §6.1 为准。
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
NOVICE_CAP = 59  # 1.1.0 的画像封顶值；1.2.0 起不应再出现
#: v0.2.5：画像类 hint 规则
PROFILE_HINT_RULES = {"SH0", "SH0B", "SH0C", "IT0B", "IT0C"}

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
    """返回 {raw, scores, caps(HorizonCap 列表/周期), gate_caps(闸门 id/周期), hints(HorizonHint 列表), suitable}。
    ``rank_pct`` 输入直接给分位值；``f.*`` 为 None 记为缺失；``profile.*`` 为 None 记为未填写。"""
    raw: dict[str, int] = {}
    scores: dict[str, int] = {}
    caps: dict[str, list[dict[str, Any]]] = {}
    gate_caps: dict[str, list[str]] = {}
    hints: list[dict[str, Any]] = []
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
            mode = q.get("mode", "cap")
            actual = inputs.get(q["input"])
            if mode == "hint":
                if actual is not None and not _cond(q["op"], actual, q.get("value")):
                    hints.append({"horizon": h, "rule_id": q["id"], "text": q["reason"]})
                continue
            if not _cond(q["op"], actual, q.get("value")):
                if "else_score" in q:
                    zero = True
                    cap = q["else_score"]
                else:
                    cap = q["else_cap"]
                    limits.append((cap, q["id"]))
                hcaps.append({"horizon": h, "cap": cap, "kind": "requires", "rule_id": q["id"], "inputs_missing": []})
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
    return {"raw": raw, "scores": scores, "caps": caps, "gate_caps": gate_caps, "hints": hints, "suitable": suitable}


def hint_ids(r: dict[str, Any], horizon: str | None = None) -> set[str]:
    return {x["rule_id"] for x in r["hints"] if horizon is None or x["horizon"] == horizon}


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


#: 画像全空（v0.2.5：未填写 → 不封顶、不提示）
EMPTY_PROFILE = {"profile.horizon_pref": None, "profile.effort": None, "profile.risk_tolerance": None, "profile.experience": None}
#: 画像全部满足画像类规则
FULL_PROFILE = {"profile.effort": "high", "profile.risk_tolerance": 4, "profile.experience": "advanced"}


def _profile_rules() -> list[tuple[str, dict[str, Any]]]:
    return [(h, q) for h in HORIZONS for q in RULES["horizons"][h]["requires"] if q["input"].startswith("profile.")]


def test_snapshot_is_classifier_1_2_0():
    """v0.2.5 组 4：``version_no: 3``、``classifier_version: "1.2.0"``。"""
    assert (CFG["version_no"], CFG["classifier_version"]) == (3, "1.2.0")


@pytest.mark.parametrize(("horizon", "rule_id", "input_key", "op", "value"), [
    ("short", "SH0", "profile.risk_tolerance", "ge", 3),
    ("short", "SH0B", "profile.effort", "in", ["medium", "high"]),
    ("short", "SH0C", "profile.experience", "in", ["intermediate", "advanced"]),
    ("intraday_t", "IT0B", "profile.effort", "in", ["medium", "high"]),
    ("intraday_t", "IT0C", "profile.experience", "in", ["intermediate", "advanced"]),
])
def test_profile_rules_are_hint_mode_without_else_cap(horizon, rule_id, input_key, op, value):
    """v0.2.5 组 4：SH0/SH0B/SH0C/IT0B/IT0C 为 ``mode: hint``，不带 ``else_cap`` / ``else_score``。"""
    rule = next(q for q in RULES["horizons"][horizon]["requires"] if q["id"] == rule_id)
    assert (rule["input"], rule["op"], rule["value"], rule.get("mode")) == (input_key, op, value, "hint")
    assert "else_cap" not in rule and "else_score" not in rule
    assert isinstance(rule["reason"], str) and rule["reason"]


def test_all_profile_rules_are_hints_and_cap_rules_keep_else():
    """所有 ``profile.*`` 规则都是 hint（共 5 条）；其余 requires（如 IT0、LG0）仍为 cap 模式且带 else_cap/else_score。"""
    assert {q["id"] for _, q in _profile_rules()} == PROFILE_HINT_RULES
    assert all(q.get("mode") == "hint" for _, q in _profile_rules())
    for h in HORIZONS:
        for q in RULES["horizons"][h]["requires"]:
            if q.get("mode", "cap") == "cap":
                assert ("else_cap" in q) != ("else_score" in q), q["id"]
            assert q.get("mode", "cap") in {"cap", "hint"}


def test_case_b_unchanged():
    r = evaluate(CASE_B)
    assert r["scores"] == {"intraday_t": 100, "short": 100, "swing": 70, "long": 20}
    assert r["suitable"] == ["short", "intraday_t", "swing"] and r["hints"] == []


def test_empty_profile_no_59_cap_and_no_hints():
    """v0.2.5 组 4：画像全空时 short/intraday_t 与“画像全满足”相比只差加分项（不出现 59 封顶），``hints=[]``。"""
    empty = evaluate({**CASE_B, **EMPTY_PROFILE})
    full = evaluate({**CASE_B, **FULL_PROFILE})
    assert empty["hints"] == []
    for h in ("short", "intraday_t"):
        assert not [c for c in empty["caps"][h] if c["rule_id"] in PROFILE_HINT_RULES]
        assert empty["scores"][h] == empty["raw"][h] and empty["scores"][h] != NOVICE_CAP
        assert empty["scores"][h] <= full["scores"][h]  # 只差画像加分项（如 SH4 偏好）
    assert "short" in empty["suitable"] and "intraday_t" in empty["suitable"]


@pytest.mark.parametrize("base", ["B", "E"])
def test_novice_hints_sh0c_it0c_without_caps_and_suitable_unchanged(base):
    """v0.2.5 组 4：``experience=novice`` → hints 含 SH0C、IT0C；caps 不含二者；suitable 与非 novice 时相同。"""
    case = CASE_B if base == "B" else CASE_E
    novice = evaluate({**case, "profile.experience": "novice"})
    control = evaluate({**case, "profile.experience": "advanced"})
    assert {"SH0C", "IT0C"} <= hint_ids(novice)
    assert hint_ids(novice, "short") >= {"SH0C"} and hint_ids(novice, "intraday_t") >= {"IT0C"}
    for h in HORIZONS:
        assert not {"SH0C", "IT0C"} & set(rule_ids(novice["caps"][h]))
    assert novice["suitable"] == control["suitable"]  # 分数可因经验加分项不同（如 intraday_t），但无 59 封顶
    assert all(novice["scores"][h] == novice["raw"][h] or novice["gate_caps"][h] or novice["caps"][h] for h in HORIZONS)
    assert_horizon_cap_shape(novice)


def test_risk_tolerance_2_hints_sh0():
    r = evaluate({**CASE_B, "profile.risk_tolerance": 2})
    assert hint_ids(r) == {"SH0"} and r["hints"][0]["horizon"] == "short"
    assert r["scores"] == evaluate(CASE_B)["scores"]


def test_effort_low_hints_sh0b_and_it0b():
    r = evaluate({**CASE_B, "profile.effort": "low"})
    assert hint_ids(r, "short") == {"SH0B"} and hint_ids(r, "intraday_t") == {"IT0B"}
    assert r["suitable"] == evaluate(CASE_B)["suitable"]


def test_hint_shape_is_horizon_hint():
    """契约 v0.2.5 ``HorizonHint`` = ``{horizon, rule_id, text}``；text 为规则的中文 reason；rule_id 不是 reason_code。"""
    r = evaluate({**CASE_B, "profile.experience": "novice", "profile.effort": "low", "profile.risk_tolerance": 1})
    assert hint_ids(r) == PROFILE_HINT_RULES
    for x in r["hints"]:
        assert set(x) == {"horizon", "rule_id", "text"} and x["horizon"] in HORIZONS
        assert isinstance(x["text"], str) and x["text"] and "未填写" not in x["text"]


def test_it0_no_base_position_still_in_caps_as_requires():
    """v0.2.5 组 4：IT0（无底仓）仍是 ``mode: cap``，在 caps 中 ``kind=requires``，分数 0。"""
    r = evaluate({**CASE_B, "user.has_position": False})
    assert {"horizon": "intraday_t", "cap": 0, "kind": "requires", "rule_id": "IT0", "inputs_missing": []} in r["caps"]["intraday_t"]
    assert r["scores"]["intraday_t"] == 0 and "intraday_t" not in r["suitable"]
    assert_horizon_cap_shape(r)


def test_case_e_under_1_2_0():
    """用例 E（novice 次新股）：1.2.0 起 short 不再封顶（85，适合），只提示 SH0C；intraday_t 无底仓 IT0 → 0；swing 被 HG6 封顶 59。"""
    r = evaluate(CASE_E)
    assert r["raw"]["short"] == 85 and r["raw"]["swing"] == 65
    assert r["scores"] == {"intraday_t": 0, "short": 85, "swing": 59, "long": 10}
    assert r["caps"]["short"] == []
    assert rule_ids(r["caps"]["intraday_t"]) == ["IT0"]
    assert r["gate_caps"]["swing"] == ["HG6"] and r["caps"]["swing"] == []  # 闸门封顶不是 HorizonCap
    assert hint_ids(r) == {"SH0C", "IT0C"} and r["suitable"] == ["short"]
    assert_horizon_cap_shape(r)


def test_experience_unfilled_no_hint_no_cap():
    """v0.2.5：经验未填写 → 不再按 novice 处理（不封顶、不提示）。"""
    r = evaluate({**CASE_E, "profile.experience": None})
    assert r["scores"]["short"] == 85 and r["hints"] == [] and r["suitable"] == ["short"]


def test_rule_ids_are_not_reason_codes():
    """#23：画像类规则 ID 只出现在 HorizonHint.rule_id / HorizonCap.rule_id，快照里不出现在任何 reason_code 字段。"""
    for _, rule in _profile_rules():
        assert "reason_code" not in rule
    blob = SNAP.read_text(encoding="utf-8")
    assert not re.search(r"reason_code[^\n]*(SH0|IT0)", blob)
