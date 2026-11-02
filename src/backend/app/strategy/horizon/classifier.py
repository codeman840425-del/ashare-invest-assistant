"""周期分类器规则求值（纯函数，不碰数据库；classifier 1.2.0 = ``horizon_classifier.yaml`` v3）。

判定顺序（horizon_classifier.md §3/§4，契约 v0.2.5/v0.2.6 §5.1 ``HorizonCap``/``HorizonHint``）：

1. 闸门 ``gates``：按顺序全部求值；命中 ``score: 0`` → 该周期 0 分（HG1–HG3 记
   ``cap: 0``），命中 ``cap`` → 封顶。都写入 ``caps[]``，``kind: gate``、``rule_id: HGn``、
   ``inputs_missing: []``。
2. 前提 ``requires``：
   - ``mode: hint``（画像类）：输入未填写 → 跳过；已填写且不满足 → 只写 ``hints[]``，
     不改分数、不进 ``caps[]``、不影响 ``suitable``（与分数无关：周期已判 0 分照样提示）。
   - ``else_score: 0``（IT0）：不满足 → 0 分，**不进** ``caps[]``，只写反向理由。
   - ``else_cap``（LG0/LG0B）：不满足 → 封顶，``kind: data_missing``、``rule_id`` 为规则 ID。
3. 组件 ``components``：每个取第一个命中的分档；``f.*`` 为 null 记缺失，缺失组件的满分合计
   ≥ ``data_missing_cap.missing_points_ge`` → 封顶 ``data_missing_cap.cap``
   （``kind: data_missing``、``rule_id: null``、``inputs_missing`` 为该周期缺失的 ``f.*`` 键）。
   ``sec.*``/``user.*``/``profile.*`` 为 null 只是不计分，不进 ``inputs_missing``。
4. 分数 = 0（判 0）或 min(原始分, 全部封顶)；``suitable`` = 分数 ≥ ``suitable_threshold``，
   按分数降序、同分按 ``tie_order``。

``transform: rank_pct`` 的输入由调用方给出已换算的分位值（全市场截面，见 ``rank_pct_universe``）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.config_files import (
    HORIZON_NAMES,
    ClassifierComponent,
    HorizonClassifierConfig,
    HorizonRules,
    HorizonRuleSet,
    RuleOp,
)

Polarity = Literal["for", "against"]


def cond(op: RuleOp, actual: Any, value: Any) -> bool:  # noqa: ANN401 - 规则输入是异构标量
    """horizon_classifier.md §4 比较语义；``actual`` 为 null 时只有 ``not_null`` 可判（为假）。"""
    if op == "not_null":
        return actual is not None
    if actual is None:
        return False
    try:
        if op == "eq":
            return bool(actual == value)
        if op == "ne":
            return bool(actual != value)
        if op == "lt":
            return bool(actual < value)
        if op == "le":
            return bool(actual <= value)
        if op == "gt":
            return bool(actual > value)
        if op == "ge":
            return bool(actual >= value)
        if op == "in":
            return actual in value
        if op == "contains":
            return value in actual
        if op == "between":
            return bool(value[0] <= actual <= value[1])
    except TypeError:
        return False
    raise ValueError(f"unknown op {op}")


@dataclass(frozen=True)
class Reason:
    horizon: str
    polarity: Polarity
    text: str
    #: 理由所依据的输入键（调用方据此挂 ``evidence_ids``）
    input: str | None
    #: 排序权重：越大越靠前
    weight: int


@dataclass
class Result:
    classifier_version: str
    raw: dict[str, int]
    scores: dict[str, int]
    caps: list[dict[str, Any]]
    hints: list[dict[str, str]]
    suitable: list[str]
    inputs_missing: list[str]
    reasons: list[Reason] = field(default_factory=list)


# ------------------------------------------------------------------ 文案


def _fmt_scalar(v: Any) -> str:  # noqa: ANN401
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float | Decimal):
        return f"{float(v):g}"
    return str(v)


def render(template: str, value: Any) -> str:  # noqa: ANN401
    """组件文案占位：``{v}``、``{v:pct}``（分位 → 百分数）、``{v:yi}``（元 → 亿元）、
    ``{v:has}``（有/无）。
    """
    if isinstance(value, list | tuple):
        plain = "、".join(_fmt_scalar(x) for x in value)
    else:
        plain = _fmt_scalar(value)
    out = template
    if "{v:pct}" in out:
        out = out.replace("{v:pct}", f"{round(float(value) * 100)}%")
    if "{v:yi}" in out:
        out = out.replace("{v:yi}", f"{float(value) / 1e8:.2f}")
    if "{v:has}" in out:
        out = out.replace("{v:has}", "有" if value else "无")
    return out.replace("{v}", plain)


def _missing_text(c: ClassifierComponent) -> str:
    return f"数据暂缺（{c.input}）：本项 {c.max_pts} 分不计入"


# ------------------------------------------------------------------ 求值


def _horizon_rules(rules: HorizonRules, h: str) -> HorizonRuleSet:
    rs: HorizonRuleSet = getattr(rules.horizons, h)
    return rs


def classify(cfg: HorizonClassifierConfig, inputs: Mapping[str, Any]) -> Result:
    """按 ``cfg.rules`` 求值。``cfg.rules`` 为 None（规则未配置）时四周期 0 分、不输出“适合”。"""
    rules = cfg.rules
    raw: dict[str, int] = {}
    scores: dict[str, int] = {}
    caps: list[dict[str, Any]] = []
    hints: list[dict[str, str]] = []
    reasons: list[Reason] = []
    all_missing: set[str] = set()
    if rules is None:
        nil: dict[str, int] = dict.fromkeys(HORIZON_NAMES, 0)
        return Result(cfg.classifier_version, nil, dict(nil), [], [], [], [])
    for h in HORIZON_NAMES:
        spec = _horizon_rules(rules, h)
        zero = False
        limits: list[int] = []
        for g in rules.gates:
            if g.horizons != "all" and h not in g.horizons:
                continue
            if not cond(g.op, inputs.get(g.input), g.value):
                continue
            if g.score is not None:
                zero = True
                cap = 0
            else:
                assert g.cap is not None  # noqa: S101 - 模型校验保证二选一
                cap = g.cap
                limits.append(cap)
            caps.append(
                {"horizon": h, "cap": cap, "kind": "gate", "rule_id": g.id, "inputs_missing": []}
            )
            reasons.append(Reason(h, "against", g.reason, g.input, 1000))
        for q in spec.requires:
            actual = inputs.get(q.input)
            if q.mode == "hint":
                if actual is not None and not cond(q.op, actual, q.value):
                    hints.append({"horizon": h, "rule_id": q.id, "text": q.reason})
                continue
            if cond(q.op, actual, q.value):
                continue
            if q.else_score is not None:
                zero = True  # 分数，不是封顶：不进 caps，只写反向理由
                reasons.append(Reason(h, "against", q.reason, q.input, 900))
                continue
            assert q.else_cap is not None  # noqa: S101
            limits.append(q.else_cap)
            caps.append(
                {
                    "horizon": h,
                    "cap": q.else_cap,
                    "kind": "data_missing",
                    "rule_id": q.id,
                    "inputs_missing": [],
                }
            )
            reasons.append(Reason(h, "against", q.reason, q.input, 800))
        total = missing_pts = 0
        missing_keys: set[str] = set()
        for c in spec.components:
            v = inputs.get(c.input)
            if v is None:
                if c.input.startswith("f."):
                    missing_pts += c.max_pts
                    missing_keys.add(c.input)
                    reasons.append(Reason(h, "against", _missing_text(c), None, c.max_pts))
                continue
            pts = next((b.pts for b in c.bands if cond(b.op, v, b.value)), 0)
            total += pts
            text = render(c.text, v)
            if pts > 0:
                reasons.append(Reason(h, "for", text, c.input, 500 + pts))
            else:
                reasons.append(Reason(h, "against", text, c.input, 100 + c.max_pts))
        dm = rules.data_missing_cap
        if missing_pts >= dm.missing_points_ge:
            limits.append(dm.cap)
            caps.append(
                {
                    "horizon": h,
                    "cap": dm.cap,
                    "kind": "data_missing",
                    "rule_id": None,
                    "inputs_missing": sorted(missing_keys),
                }
            )
        all_missing |= missing_keys
        raw[h] = total
        scores[h] = 0 if zero else min([total, *limits])
    order: dict[str, int] = {h: i for i, h in enumerate(rules.tie_order)}
    suitable: list[str] = sorted(
        (h for h in HORIZON_NAMES if scores[h] >= cfg.suitable_threshold),
        key=lambda h: (-scores[h], order[h]),
    )
    return Result(
        classifier_version=cfg.classifier_version,
        raw=raw,
        scores=scores,
        caps=caps,
        hints=hints,
        suitable=suitable,
        inputs_missing=sorted(all_missing),
        reasons=_pick_reasons(reasons, cfg.reasons_per_horizon),
    )


def _pick_reasons(reasons: list[Reason], bounds: tuple[int, int]) -> list[Reason]:
    """每个周期 ``reasons_per_horizon``（默认 2–4）条：闸门/前提的反向理由最先，其次按权重。"""
    lo, hi = bounds
    out: list[Reason] = []
    for h in HORIZON_NAMES:
        mine = sorted(
            (r for r in reasons if r.horizon == h),
            key=lambda r: -r.weight,
        )
        picked = mine[:hi]
        if len(picked) < lo:  # 规则保证每周期至少 2 个组件；防御：不足时照实返回
            picked = mine
        out.extend(picked)
    return out


__all__ = ["Reason", "Result", "classify", "cond", "render"]
