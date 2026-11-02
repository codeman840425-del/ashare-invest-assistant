"""研究候选版本的系统生成内容（契约 v0.2.9 §7.7A“系统生成的内容”，T-B10）。

每次新建版本时按当时数据生成一次，写入该版本的快照（``data_snapshots.purpose='candidate'``，
带本人 ``user_id``），之后不刷新：

- ``origin=suggestion``：``reasons`` = 来源建议各策略结论 ``strategies[].reasons``；
  ``counter_evidence`` = 各策略结论 ``counter_evidence`` + 建议 ``risk_flags``；原文与证据照抄
  （建议的 ``evidence[]`` 原样并入本版本 ``evidence[]``）。
- ``manual`` / ``from_stock``：``reasons=[]``；``counter_evidence`` 只列证券风险因子：
  主数据 ``risk_flag``（ST / *ST / 退市风险警示）与
  ``listing_status=delisting_period``（退市整理）。
  停牌：证券主数据没有停牌字段、行情未接入 → 不列，``gaps`` 写明。
- ``fit_assessment``：只读本人画像、本人持仓、本人风控上限。
  ``hints`` 与 ``/horizon-assessments`` 同规则（画像已填写才求值）；
  ``warnings``：本人已持有该证券时对照 RC2 ``position_cap`` 上限的提示。
  RC4 同行业：行业数据未接入 → 不判定、不静默：RC4 启用时 ``gaps`` 列
  ``{key:"fit_assessment.sector", reason:"no_source"}``（plan 4.2 T-O11 裁定，T-B49）。
- 数据状态：本版内容只用“证券公开主数据 + 本人记录（建议、画像、持仓）”，不用任何证书数据
  （行情、因子未接入研究候选）。按 §1.1 混合来源规则，证书部分从未取到 → ``data_status=partial``，
  ``gaps`` 给出 ``data_licence_unavailable``（本人证书不可用）或 ``not_yet_published``（证书可用，
  但研究候选尚未接入行情）。快照 ``licence_id`` 为 null（没有使用证书）。

生成的事实另以 ``claims`` + ``claim_links``（``target_type=candidate_version``，
``role`` = ``reason`` / ``counter`` / ``risk``）存储，``claims.user_id`` 一律为本人。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import Connection, Row, exists, func, insert, select

from app.auth.service import bj, latest_profile, now_utc
from app.config import Settings
from app.db.tables.accounts import accounts, broker_position_snapshots, holdings
from app.db.tables.research import claim_links, claims
from app.db.tables.reviews import data_snapshots
from app.licences.service import live_status
from app.strategy.horizon import classifier
from app.strategy.horizon import inputs as hz_inputs

#: 本模块生成的证据 id 前缀（与照抄的建议证据 id 区分，避免撞号）
EV_PREFIX: Final = "rc-e"

_RISK_TEXT: Final = {
    "st": "该证券被实施其他风险警示（ST）",
    "star_st": "该证券被实施退市风险警示（*ST）",
    # T-O11 裁定 / 契约 #29 ①：delisting 是退市整理标记（不是 *ST），最终文案（T-B49）
    "delisting": "该证券处于退市整理期（简称带“退”）",
}


@dataclass
class Fact:
    """一条 ``CandidateFact`` + 它在 ``claim_links`` 里的角色。"""

    role: str  # reason / counter / risk
    text: str
    evidence_ids: list[str]
    epistemic_type: str = "fact"
    source_kind: str = "system_calc"

    def out(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence_ids": list(self.evidence_ids),
            "epistemic_type": self.epistemic_type,
            "source_kind": self.source_kind,
        }


@dataclass
class Content:
    name: str
    reasons: list[Fact] = field(default_factory=list)
    counter: list[Fact] = field(default_factory=list)
    fit: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    data_status: str = "partial"
    data_as_of: str | None = None
    gaps: list[dict[str, str]] = field(default_factory=list)

    def items(self) -> dict[str, Any]:
        """写入快照 ``items`` 的冻结内容（回看只读这里）。"""
        return {
            "name": self.name,
            "reasons": [f.out() for f in self.reasons],
            "counter_evidence": [f.out() for f in self.counter],
            "fit_assessment": self.fit,
            "evidence": self.evidence,
            "data_status": self.data_status,
            "data_as_of": self.data_as_of,
            "gaps": self.gaps,
        }


@dataclass(frozen=True)
class SecStub:
    """证券已不在主数据时的替身（名称退回代码，不列风险因子）。"""

    name: str
    risk_flag: str | None = None
    listing_status: str | None = None
    master_as_of: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class _Ev:
    def __init__(self, fetched: dt.datetime) -> None:
        self.items: list[dict[str, Any]] = []
        self.fetched = fetched

    def add(
        self,
        key: str,
        value: Any,  # noqa: ANN401 - 证据值为异构标量
        provider: str,
        as_of: dt.datetime | None,
        epistemic: str = "fact",
    ) -> str:
        eid = f"{EV_PREFIX}{len(self.items) + 1}"
        self.items.append(
            {
                "id": eid,
                "key": key,
                "value": value,
                "unit": None,
                "provider": provider,
                "endpoint": None,
                "data_as_of": bj(as_of or self.fetched),
                "fetched_at": bj(self.fetched),
                "epistemic_type": epistemic,
            }
        )
        return eid


def _text_items(raw: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - jsonb
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw:
        if isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"].strip():
            ids = x.get("evidence_ids")
            out.append(
                {
                    "text": x["text"],
                    "evidence_ids": [str(i) for i in ids] if isinstance(ids, list) else [],
                    "epistemic_type": x.get("epistemic_type")
                    if x.get("epistemic_type") in ("fact", "estimate")
                    else "fact",
                }
            )
    return out


def _from_suggestion(sug: Row[Any], c: Content) -> None:
    ev = sug.evidence if isinstance(sug.evidence, list) else []
    known = {str(e.get("id")) for e in ev if isinstance(e, dict) and e.get("id") is not None}
    c.evidence.extend(e for e in ev if isinstance(e, dict))

    def fact(x: dict[str, Any], role: str) -> Fact:
        # 只保留能在本版本 evidence[] 里找到的 id（契约：evidence_ids 都能找到）
        ids = [i for i in x["evidence_ids"] if i in known]
        return Fact(role, x["text"], ids, x["epistemic_type"], "system_calc")

    seen: set[tuple[str, str]] = set()
    for s in sug.strategies if isinstance(sug.strategies, list) else []:
        if not isinstance(s, dict):
            continue
        for x in _text_items(s.get("reasons")):
            if ("reason", x["text"]) not in seen:
                seen.add(("reason", x["text"]))
                c.reasons.append(fact(x, "reason"))
        for x in _text_items(s.get("counter_evidence")):
            if ("counter", x["text"]) not in seen:
                seen.add(("counter", x["text"]))
                c.counter.append(fact(x, "counter"))
    for x in _text_items(sug.risk_flags):
        if ("risk", x["text"]) not in seen:
            seen.add(("risk", x["text"]))
            c.counter.append(fact(x, "risk"))


def _security_risks(sec: Row[Any] | SecStub, c: Content, evs: _Ev) -> None:
    s_at = sec.master_as_of or sec.updated_at
    if sec.risk_flag in _RISK_TEXT:
        eid = evs.add("sec.risk_flag", sec.risk_flag, "exchange", s_at)
        c.counter.append(Fact("risk", _RISK_TEXT[sec.risk_flag], [eid], "fact", "disclosure"))
    if sec.listing_status == "delisting_period":
        eid = evs.add("sec.listing_status", sec.listing_status, "exchange", s_at)
        c.counter.append(Fact("risk", "该证券处于退市整理期", [eid], "fact", "disclosure"))


def _fit(
    conn: Connection, settings: Settings, user_id: uuid.UUID, code: str, evs: _Ev
) -> dict[str, Any]:
    prof = latest_profile(conn, user_id)
    hints: list[dict[str, str]] = []
    if prof is not None:
        cfg = settings.business.horizon_classifier
        got = hz_inputs.collect(conn, user_id, code, list(cfg.features))
        hints = [dict(h) for h in classifier.classify(cfg, got.values).hints]

    acc_ids = select(accounts.c.id).where(
        accounts.c.user_id == user_id, accounts.c.archived_at.is_(None)
    )
    holdings_available = bool(
        conn.execute(
            select(
                exists().where(holdings.c.account_id.in_(acc_ids))
                | exists().where(broker_position_snapshots.c.account_id.in_(acc_ids))
            )
        ).scalar()
    )
    warnings: list[dict[str, Any]] = []
    rc2 = settings.business.risk_controls.rc2_position_cap
    if holdings_available and rc2.enabled:
        qty, at = conn.execute(
            select(func.sum(holdings.c.quantity), func.max(holdings.c.rebuilt_at)).where(
                holdings.c.account_id.in_(acc_ids),
                holdings.c.security_code == code,
                holdings.c.quantity > 0,
            )
        ).one()
        if qty:
            cap: Decimal = rc2.single_position_max_pct
            cap_src, cap_at = "system", None
            if prof is not None and prof.max_single_position_pct is not None:
                cap = Decimal(prof.max_single_position_pct)
                cap_src, cap_at = "user_input", prof.confirmed_at or prof.created_at
            q = format(Decimal(qty).normalize(), "f")
            c_txt = format(cap.normalize(), "f")
            e1 = evs.add("user.position_qty", q, "user_import", at)
            e2 = evs.add("risk.rc2_position_cap_pct", c_txt, cap_src, cap_at)
            warnings.append(
                {
                    "text": f"你已持有该证券 {q} 股；单一持仓上限为总资产的 {c_txt}%"
                    "（RC2 position_cap），加仓前请对照",
                    "evidence_ids": [e1, e2],
                }
            )
    return {
        "profile_filled": prof is not None,
        "holdings_available": holdings_available,
        "hints": hints,
        "warnings": warnings,
    }


def generate(
    conn: Connection,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    code: str,
    sec: Row[Any] | SecStub,
    suggestion: Row[Any] | None,
) -> Content:
    now = now_utc()
    evs = _Ev(now)
    c = Content(name=str(sec.name))
    if suggestion is not None:
        _from_suggestion(suggestion, c)
    else:
        _security_risks(sec, c, evs)
    c.fit = _fit(conn, settings, user_id, code, evs)
    c.evidence.extend(evs.items)

    as_of = [sec.master_as_of or sec.updated_at]
    if suggestion is not None:
        as_of.append(suggestion.created_at)
    c.data_as_of = bj(max(a for a in as_of if a is not None)) if any(as_of) else None
    lic_ok = live_status(conn, user_id) == "active"
    c.data_status = "partial"
    c.gaps = [
        {
            "key": "market_data",
            "reason": "not_yet_published" if lic_ok else "data_licence_unavailable",
            "message": "研究候选本版只用证券主数据与本人记录，行情、因子类规则尚未接入"
            if lic_ok
            else "你的数据证书不可用；研究候选本版只用证券主数据与本人记录",
        },
        {
            "key": "suspension",
            "reason": "not_yet_published",
            "message": "停牌状态尚未接入，反证未列停牌",
        },
    ]
    # T-B49（plan 4.2「研究候选 RC4 的行业与停牌数据来源」）：行业数据接入前 RC4 照常出 gap
    if settings.business.risk_controls.rc4_sector_concentration.enabled:
        c.gaps.append(
            {
                "key": "fit_assessment.sector",
                "reason": "no_source",
                "message": "行业分类数据尚未接入，未做同行业集中度（RC4）提示",
            }
        )
    return c


def snapshot_hash(items: dict[str, Any]) -> str:
    raw = json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_snapshot(conn: Connection, user_id: uuid.UUID, items: dict[str, Any]) -> uuid.UUID:
    sid = uuid.uuid4()
    conn.execute(
        insert(data_snapshots).values(
            id=sid,
            purpose="candidate",
            items=items,
            hash=snapshot_hash(items),
            user_id=user_id,
            licence_id=None,
        )
    )
    return sid


def write_claims(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    code: str,
    version_id: uuid.UUID,
    content: Content,
    snapshot_id: uuid.UUID,
) -> None:
    """系统生成的事实 → ``claims``（本人 ``user_id``）+ ``claim_links``。"""
    for f in [*content.reasons, *content.counter]:
        cid = uuid.uuid4()
        conn.execute(
            insert(claims).values(
                id=cid,
                user_id=user_id,
                security_code=code,
                statement=f.text,
                epistemic_type=f.epistemic_type,
                source_kind=f.source_kind,
                source_ref={"snapshot_id": str(snapshot_id), "evidence_ids": f.evidence_ids},
            )
        )
        conn.execute(
            insert(claim_links).values(
                claim_id=cid, target_type="candidate_version", target_id=version_id, role=f.role
            )
        )
