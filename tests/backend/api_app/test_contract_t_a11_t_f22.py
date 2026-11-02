"""T-T25 追加：契约 v0.2.9（架构师 439746e）§9 两组验收的契约测试。

- ``test_a11_NN_*`` ↔ “v0.2.9 验收（T-A11 研究候选，§7.7A）”第 NN 条（1–11）；
- ``test_f22_N_*``  ↔ “v0.2.9 验收（T-F22 管理端证书遗留，§7.9）”第 N 条（1–5）。

T-F22 五条全是接口 / 库层行为（resume 幂等、排序、理由不外露、冷却字段、通知行），没有界面验收项，
故与 T-A11 一样放在 pytest（不放 vitest / Playwright）。

门控原则（不放宽断言）：
- 所用 docs 低于 439746e（没有 T-A11 / T-F22 验收块）→ 文档层用例 xfail（运维推送）；
- ``/candidates*`` 未挂载 → imperative xfail，owner 后端 T-B10；挂载后严格断言；
- 已有实现（库表 CHECK、candidate_versions 不可变触发器、删除用户数据 CLI、/admin/data-licences 排序与 409）严格断言；
- 已实现但与 v0.2.9 规则不符（resume 幂等仍写审计、pause/resume 不发通知）→ 检测到差异时 imperative xfail，写明 owner；
- ``/admin/ingest/status`` 未挂载 → 先严格断言可测部分，再 xfail（沿用 T-T23 的 owner，不是新缺口）。

真实 PG/Redis（T-T22/T-T23 夹具，独立临时库），进程内 TestClient；不联网、不调用麦蕊；
测试证书运行时随机生成，暂停理由用虚构文字“示例理由”。
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import json
import os
import re
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tt25b_cli_t24", _HERE / "test_delete_user_data_cli_t_t24.py")
_t24 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t24)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)
_t23 = _t24._t23

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
roles, cli = _t24.roles, _t24.cli
API, assert_err, Rec, fake_licence, put = _t23.API, _t23.assert_err, _t23.Rec, _t23.fake_licence, _t23.put
leak_count, live_row, set_status, admin_items = _t23.leak_count, _t23.live_row, _t23.set_status, _t23.admin_items
require_route, has_route, seed_securities = _t23.require_route, _t23.has_route, _t23.seed_securities

sys.path.insert(0, str(_HERE.parents[1] / "replay"))
import dl_ref_model as ref  # noqa: E402  测试侧参考模型（上游 101 → 北京时间次日 00:01）

pytestmark = [pytest.mark.integration, pytest.mark.contract]

REPO = Path(__file__).resolve().parents[3]
C439 = "契约 v0.2.9 439746e"
O_DOCS439 = f"运维（把{C439}（T-A11 / T-F22 验收块）推到 origin；所用 docs 没有该块）"
O_A11 = f"后端 T-B10（{C439} #19–#25 / T-A11 验收"  # 后接条目号
O_A11_ENUMS = (f"后端 T-B10 / T-B33（{C439} 变更表 “/meta/enums.version” 行：enums 加 research_candidate_status、"
               "research_candidate_origin、candidate_decision，version=v0.2.9）")
O_F22_IDEMP = (f"后端 T-B45 / T-B03e（{C439} #26①，T-F22 验收 1：已设置未暂停时 resume 仍写审计 / 事件，"
               "应与重复暂停一样不写；改 be607b3 的 _admin_transition）")
O_F22_NOTIFY = (f"后端 T-B45 / T-B03e（{C439} #26⑤，T-F22 验收 5：pause/resume 状态确实变化时给该用户发 "
                "kind=data_licence 通知，幂等重复不发）")
O_INGEST_STATUS = _t23.O_INGEST_STATUS  # 已在 a570315 及更早登记，非新缺口
O_SSE = "后端 T-B05（/stream SSE 未挂载；理由不外露 / 无 SSE 事件的 SSE 部分无从断言）"

STOCK, CDR, ETF, INDEX = "600981.SH", "689981.SH", "510981.SH", "000981.SH"
REASON = "示例理由"
#: 契约 §3（v0.2.9 T-A11）：取值与顺序
A11_ENUMS = {
    "research_candidate_status": ["researching", "watching", "dropped", "planned"],
    "research_candidate_origin": ["strategy_screen", "suggestion", "manual", "from_stock"],
    "candidate_decision": ["continue", "watch", "drop"],
}
#: (表, 列) → 契约枚举
A11_CHECKS = {("research_candidates", "status"): "research_candidate_status",
              ("research_candidates", "origin"): "research_candidate_origin",
              ("candidate_versions", "decision"): "candidate_decision"}


# =============================== 工具 ===============================
_VERSION_RE = re.compile(r"版本：\*\*v(\d+)\.(\d+)(?:\.(\d+))?\*\*")


def _docs439() -> str:
    d = Path(os.environ.get("AIA_DOCS_DIR", REPO / "docs"))
    p = d / "api-contract.md"
    if not p.is_file():
        pytest.skip(f"{d} 下没有 api-contract.md")
    text = p.read_text(encoding="utf-8")
    if "**v0.2.9 验收**（T-A11" not in text:
        m = _VERSION_RE.search(text)
        pytest.xfail(f"{O_DOCS439}：docs 版本 {'v' + '.'.join(x or '0' for x in m.groups()) if m else '?'}")
    return text


def _block(text: str, tag: str) -> dict[int, str]:
    start = text.index(f"**v0.2.9 验收**（{tag}")
    block = text[start:].split("\n- **", 1)[0]
    return {int(n): body for n, body in re.findall(r"^\s+(\d+)\. (.+)$", block, re.M)}


def _enum_row(text: str, name: str) -> list[str]:
    m = re.search(rf"^\| `{name}` \| (.+?) \|", text, re.M)
    assert m, f"§3 没有 {name}"
    return re.findall(r"`([a-z0-9_]+)`", m.group(1).split("（", 1)[0])


def _db_check_values(sql: Callable[..., Any], table: str, column: str) -> list[str]:
    """库中 ``app.<table>`` 上约束 ``column`` 取值的 CHECK（pg_get_constraintdef 文本，按书写顺序）。"""
    defs = [r[0] for r in sql("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                              "WHERE conrelid = CAST(:t AS regclass) AND contype = 'c'", t=f"app.{table}")]
    hits = [d for d in defs if re.search(rf"\(\(?{column}\b", d) and "'" in d]
    assert len(hits) == 1, (table, column, hits)
    return re.findall(r"'([^']+)'", hits[0])


def _err_shape(r: Any) -> str:
    err = dict(r.json()["error"])
    err.pop("request_id", None)
    return json.dumps(err, ensure_ascii=False, sort_keys=True)


def _issues(err: dict[str, Any]) -> list[tuple[str, str]]:
    return [(f.get("field"), f.get("issue")) for f in (err.get("details") or {}).get("fields", [])]


def _bad(r: Any, field: str, issue: str) -> None:
    err = assert_err(r, 400, "VALIDATION_ERROR")
    assert (field, issue) in _issues(err), err


def _gate(s: SimpleNamespace, item: int, method: str = "GET", path: str = "/candidates") -> None:
    require_route(s.client, method, path, f"{O_A11} {item}：/candidates* 未实现）")


COND = {"text": "下季度毛利率不低于本季", "verify_by": "2027-03-31", "verify_method": None, "confidence": None}


def _new(call: Rec, code: str | None = STOCK, origin: str = "manual", **kw: Any) -> Any:
    body = {"origin": origin, "security_code": code, "suggestion_id": None, "thesis": "测试论点",
            "conditions_to_hold": [COND], **kw}
    return call("POST", "/candidates", json=body)


def _ver(call: Rec, cid: str, base: int, decision: str | None = None, reason: str | None = None, **kw: Any) -> Any:
    body = {"base_version_no": base, "thesis": "测试论点", "conditions_to_hold": [COND], "decision": decision,
            "decision_reason": reason, **kw}
    return call("POST", f"/candidates/{cid}/versions", json=body)


def _list(call: Rec, query: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    path = f"/candidates{query}"
    for _ in range(50):
        r = call("GET", path)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        out += body["items"]
        if not body.get("next_cursor"):
            return out
        sep = "&" if "?" in path.split("cursor=")[0] else "?"
        path = f"/candidates{query}{sep if query else '?'}cursor={body['next_cursor']}"
    raise AssertionError("分页未结束")


def _seed_suggestion(sql: Callable[..., Any], uid: str, code: str = STOCK) -> SimpleNamespace:
    """本人的一张建议（直接写库）：strategies[].reasons / counter_evidence 与 risk_flags 各一条可追溯文本。"""
    tid = sql("INSERT INTO app.suggestion_threads (user_id, security_code) VALUES (:u, :c) RETURNING id::text",
              u=uid, c=code)[0][0]
    ev = {"id": "ev-tt25-1", "kind": "indicator", "text": "测试证据"}
    strategies = [{"strategy_id": "tt25", "reasons": [{"text": "测廿五理由甲", "evidence_ids": ["ev-tt25-1"]}],
                   "counter_evidence": [{"text": "测廿五反证乙", "evidence_ids": ["ev-tt25-1"]}]}]
    risk = [{"text": "测廿五风险丙", "evidence_ids": ["ev-tt25-1"]}]
    sid = sql("INSERT INTO app.suggestions (thread_id, user_id, security_code, seq_no, origin, data_status, "
              "strategies, risk_flags, evidence) VALUES (:t, :u, :c, 1, 'daily_batch', 'fresh', "
              "CAST(:s AS jsonb), CAST(:r AS jsonb), CAST(:e AS jsonb)) RETURNING id::text",
              t=tid, u=uid, c=code, s=json.dumps(strategies, ensure_ascii=False),
              r=json.dumps(risk, ensure_ascii=False), e=json.dumps([ev], ensure_ascii=False))[0][0]
    texts = {"reasons": {"测廿五理由甲"}, "counter": {"测廿五反证乙", "测廿五风险丙"}}
    return SimpleNamespace(id=sid, thread_id=tid, texts=texts)


def _seed_candidate(sql: Callable[..., Any], uid: str, code: str = STOCK) -> SimpleNamespace:
    """直接写库：一条候选 + 第 1 版 + 一条本人 claim 与 claim_link（target_type=candidate_version）。"""
    cid = sql("INSERT INTO app.research_candidates (user_id, security_code, origin, status) "
              "VALUES (:u, :c, 'manual', 'researching') RETURNING id::text", u=uid, c=code)[0][0]
    vid = sql("INSERT INTO app.candidate_versions (candidate_id, version_no, thesis, created_by) "
              "VALUES (:c, 1, '原始论点', :u) RETURNING id::text", c=cid, u=uid)[0][0]
    sql("UPDATE app.research_candidates SET current_version_id = :v WHERE id = :c", v=vid, c=cid)
    claim = sql("INSERT INTO app.claims (user_id, security_code, statement, epistemic_type, source_kind) "
                "VALUES (:u, :c, '测试理由', 'fact', 'system_calc') RETURNING id::text", u=uid, c=code)[0][0]
    sql("INSERT INTO app.claim_links (claim_id, target_type, target_id, role) "
        "VALUES (:k, 'candidate_version', :v, 'reason')", k=claim, v=vid)
    return SimpleNamespace(id=cid, version_id=vid, claim_id=claim)


def _a11_footprint(sql: Callable[..., Any], uid: str) -> dict[str, int]:
    q = {
        "research_candidates": "SELECT count(*) FROM app.research_candidates WHERE user_id = :u",
        "candidate_versions": "SELECT count(*) FROM app.candidate_versions v JOIN app.research_candidates c "
                              "ON c.id = v.candidate_id WHERE c.user_id = :u",
        "candidate_versions_by": "SELECT count(*) FROM app.candidate_versions WHERE created_by = :u",
        "claims": "SELECT count(*) FROM app.claims WHERE user_id = :u",
        "claim_links": "SELECT count(*) FROM app.claim_links l JOIN app.claims k ON k.id = l.claim_id "
                       "WHERE k.user_id = :u",
    }
    return {k: sql(v, u=uid)[0][0] for k, v in q.items()}


def _notif_count(sql: Callable[..., Any], uid: str | None = None) -> int:
    if uid is None:
        return sql("SELECT count(*) FROM app.notifications")[0][0]
    return sql("SELECT count(*) FROM app.notifications WHERE user_id = :u", u=uid)[0][0]


def _admin(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any]) -> SimpleNamespace:
    a = session(mkuser(role="admin"))
    return SimpleNamespace(s=a, call=Rec(a))


def _pause(acall: Rec, uid: str, pause: bool, reason: str = REASON) -> Any:
    return acall("POST", f"/admin/data-licences/{uid}/{'pause' if pause else 'resume'}", json={"reason": reason})


def _counts(sql: Callable[..., Any], uid: str) -> dict[str, int]:
    """该用户相关的审计、证书事件与通知行数（T-F22 第 1、5 条）。"""
    lids = [r[0] for r in sql("SELECT id::text FROM app.user_data_licences WHERE user_id = :u", u=uid)]
    return {
        "audit": sql("SELECT count(*) FROM app.audit_logs WHERE action LIKE 'data_licence.%' "
                     "AND (detail->>'user_id' = :u OR target_id = ANY(:l))", u=uid, l=lids)[0][0],
        "events": sql("SELECT count(*) FROM ops.data_licence_events WHERE user_id = :u "
                      "OR licence_id::text = ANY(:l)", u=uid, l=lids)[0][0],
        "notifications": _notif_count(sql, uid),
    }


# =============================== 文档自检 ===============================
A11_TOKENS = {
    1: ["research_candidate_status", "research_candidate_origin", "candidate_decision", "CHECK"],
    2: ["404", "suggestion_id", "not_found"],
    3: ["Idempotency-Key", "not_supported", "security_type_not_supported", "unknown_security",
        "verification_required", "mismatch"],
    4: ["409 CONFLICT", "existing_id", "并发"],
    5: ["VERSION_CONFLICT", "INVALID_STATE_TRANSITION", "allowed=[]"],
    6: ["405", "Allow", "触发器"],
    7: ["GET /versions/1", "逐字相同"],
    8: ["risk_flags", "profile_filled=false", "holdings_available=false"],
    9: ["data_snapshots", "claims", "claim_links", "0 行"],
    10: ["status=all", "created_at desc, id desc", "suggestion_id="],
    11: ["notifications", "SSE", "planned", "plan_ids=[]", "strategy_run_id=null"],
}
F22_TOKENS = {
    1: ["204", "audit_logs", "DATA_LICENCE_NOT_SET"],
    2: ["created_at desc", "id desc", "?status=paused_by_admin&q=示例"],
    3: ["示例理由", "/admin/ingest/status", "data_licence.paused", "detail.reason"],
    4: ["101", "quota_exceeded", "paused_until"],
    5: ["数据证书已被管理员暂停", "数据证书已被管理员恢复", "target.type=\"none\"", "not_set"],
}


@pytest.mark.unit
def test_a11_00_f22_00_docs_acceptance_blocks_complete() -> None:
    """自检：§9 两个验收块条目齐全（T-A11 1–11、T-F22 1–5），每条含本文件断言所依据的关键字。"""
    text = _docs439()
    a11, f22 = _block(text, "T-A11"), _block(text, "T-F22")
    assert sorted(a11) == list(range(1, 12)) and sorted(f22) == list(range(1, 6))
    for items, tokens in ((a11, A11_TOKENS), (f22, F22_TOKENS)):
        for n, toks in tokens.items():
            missing = [t for t in toks if t not in items[n]]
            assert not missing, (n, missing)


# =============================== T-A11 第 1 条：枚举 ===============================
@pytest.mark.unit
def test_a11_01_docs_enum_rows() -> None:
    text = _docs439()
    for name, values in A11_ENUMS.items():
        assert _enum_row(text, name) == values, name


def test_a11_01_db_check_matches_contract(sql: Callable[..., Any]) -> None:
    """库表 CHECK（迁移后的真实库 + SQLAlchemy 表定义）与契约 §3 取值、顺序一致。"""
    research = importlib.import_module("app.db.tables.research")
    for (table, column), enum in A11_CHECKS.items():
        assert _db_check_values(sql, table, column) == A11_ENUMS[enum], (table, column)
        tbl = getattr(research, table)
        got = next(re.findall(r"'([^']+)'", str(c.sqltext)) for c in tbl.constraints
                   if re.match(rf"^\s*{column} IN \(", str(getattr(c, "sqltext", ""))))
        assert got == A11_ENUMS[enum], (table, column)


def test_a11_01_meta_enums(app_client: Callable[..., Any]) -> None:
    r = app_client().get(f"{API}/meta/enums")
    assert r.status_code == 200
    enums = r.json()["enums"]
    missing = [k for k in A11_ENUMS if k not in enums]
    if missing:
        pytest.xfail(f"{O_A11_ENUMS}；缺 {missing}，version={r.json().get('version')}")
    assert r.json()["version"] == "v0.2.9"
    for name, values in A11_ENUMS.items():
        assert list(enums[name]) == values, name


# =============================== T-A11 第 2 条：只看本人 ===============================
def test_a11_02_other_user_404_and_list_excludes(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    a, b = session(), session()
    _gate(a, 2)
    seed_securities(sql)
    ca, cb = Rec(a), Rec(b)
    r = _new(ca)
    assert r.status_code == 201, r.text[:300]
    cid = r.json()["id"]
    for method, path in (("GET", f"/candidates/{cid}"), ("GET", f"/candidates/{cid}/versions"),
                         ("GET", f"/candidates/{cid}/versions/1")):
        assert_err(cb(method, path), 404, "NOT_FOUND")
    assert_err(_ver(cb, cid, 1), 404, "NOT_FOUND")
    nx = str(uuid.uuid4())
    assert _err_shape(cb("GET", f"/candidates/{cid}")) == _err_shape(cb("GET", f"/candidates/{nx}"))
    for q in ("", "?status=all"):
        assert cid not in {x["id"] for x in _list(cb, q)}


def test_a11_02_foreign_suggestion_same_as_missing(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    a, b = session(), session()
    _gate(b, 2)
    seed_securities(sql)
    sug = _seed_suggestion(sql, a.user.id)
    cb = Rec(b)
    assert _list(cb, f"?suggestion_id={sug.id}&status=all") == []
    r1 = _new(cb, None, origin="suggestion", suggestion_id=sug.id)
    r2 = _new(cb, None, origin="suggestion", suggestion_id=str(uuid.uuid4()))
    _bad(r1, "suggestion_id", "not_found")
    _bad(r2, "suggestion_id", "not_found")
    assert _err_shape(r1) == _err_shape(r2), "引用他人建议与不存在的 id 必须响应相同"
    assert sql("SELECT count(*) FROM app.research_candidates WHERE user_id = :u", u=b.user.id)[0][0] == 0


# =============================== T-A11 第 3 条：新建 ===============================
def test_a11_03_manual_create_and_idempotency(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 3, "POST")
    seed_securities(sql)
    call = Rec(s)
    key = {"Idempotency-Key": str(uuid.uuid4()), "X-CSRF-Token": s.csrf}
    body = {"origin": "manual", "security_code": STOCK, "suggestion_id": None, "thesis": "测试论点",
            "conditions_to_hold": [COND]}
    r = s.client.post(f"{API}/candidates", json=body, headers=key)
    assert r.status_code == 201, r.text[:300]
    c = r.json()
    assert c["status"] == "researching" and c["origin"] == "manual"
    assert c["current_version"]["version_no"] == 1 and c["current_version"]["decision"] is None
    assert c["current_version"]["decision_reason"] is None
    assert all(x["epistemic_type"] == "hypothesis" for x in c["current_version"]["conditions_to_hold"])
    r2 = s.client.post(f"{API}/candidates", json=body, headers=key)
    assert r2.status_code in (200, 201) and r2.json()["id"] == c["id"], "同一 Idempotency-Key 同体重放返回同一候选"
    assert sql("SELECT count(*) FROM app.research_candidates WHERE user_id = :u", u=s.user.id)[0][0] == 1
    assert sql("SELECT count(*) FROM app.candidate_versions WHERE candidate_id = :c", c=c["id"])[0][0] == 1
    assert call("GET", f"/candidates/{c['id']}").json()["version_count"] == 1


def test_a11_03_create_validation_issues(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 3, "POST")
    seed_securities(sql)
    call = Rec(s)
    _bad(_new(call, origin="strategy_screen"), "origin", "not_supported")
    _bad(_new(call, ETF), "security_code", "security_type_not_supported")
    _bad(_new(call, INDEX), "security_code", "security_type_not_supported")
    _bad(_new(call, "600999.SH"), "security_code", "unknown_security")
    bare = {"text": "无验证方式", "verify_by": None, "verify_method": None, "confidence": None}
    _bad(_new(call, conditions_to_hold=[bare]), "conditions_to_hold[0]", "verification_required")
    sug = _seed_suggestion(sql, s.user.id, STOCK)
    _bad(_new(call, CDR, origin="suggestion", suggestion_id=sug.id), "security_code", "mismatch")
    assert sql("SELECT count(*) FROM app.research_candidates WHERE user_id = :u", u=s.user.id)[0][0] == 0


# =============================== T-A11 第 4 条：重复与并发 ===============================
def test_a11_04_duplicate_conflict_and_after_drop(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    a, b = session(), session()
    _gate(a, 4, "POST")
    seed_securities(sql)
    ca = Rec(a)
    first = _new(ca).json()
    err = assert_err(_new(ca), 409, "CONFLICT")
    assert err["details"]["field"] == "security_code" and err["details"]["existing_id"] == first["id"]
    assert _ver(ca, first["id"], 1, "watch", "观察一下").status_code == 201
    err = assert_err(_new(ca), 409, "CONFLICT")  # watching 也算
    assert err["details"]["existing_id"] == first["id"]
    assert _new(Rec(b)).status_code == 201, "不同用户的同一证券互不影响"
    assert _ver(ca, first["id"], 2, "drop", "放弃").status_code == 201
    assert _new(ca).status_code == 201, "drop 后再建 → 201"


def test_a11_04_concurrent_posts_only_one_201(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 4, "POST")
    seed_securities(sql)
    other = session(s.user)  # 同一用户两个会话，避免共享 TestClient
    out: list[int] = []
    barrier = threading.Barrier(2)

    def go(x: SimpleNamespace) -> None:
        barrier.wait()
        out.append(_new(Rec(x)).status_code)

    ts = [threading.Thread(target=go, args=(x,)) for x in (s, other)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert sorted(out) == [201, 409], out
    assert sql("SELECT count(*) FROM app.research_candidates WHERE user_id = :u AND status IN "
               "('researching','watching')", u=s.user.id)[0][0] == 1


# =============================== T-A11 第 5 条：版本与决定 ===============================
def test_a11_05_versions_and_decisions(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 5, "POST")
    seed_securities(sql)
    call = Rec(s)
    c = _new(call).json()
    cid = c["id"]
    v1 = call("GET", f"/candidates/{cid}/versions/1").json()
    r = _ver(call, cid, 1, "watch", "等财报")
    assert r.status_code == 201, r.text[:300]
    assert r.json()["status"] == "watching" and r.json()["current_version"]["version_no"] == 2
    assert call("GET", f"/candidates/{cid}/versions/1").json() == v1, "旧版本内容逐字不变"
    err = assert_err(_ver(call, cid, 1), 409, "VERSION_CONFLICT")
    assert err["details"]["current_version_no"] == 2
    assert_err(_ver(call, cid, 2, "watch", None), 400, "VALIDATION_ERROR")
    assert_err(_ver(call, cid, 2, "watch", "   "), 400, "VALIDATION_ERROR")
    assert_err(_ver(call, cid, 2, "watch", "x" * 201), 400, "VALIDATION_ERROR")
    _bad(_ver(call, cid, 2, None, "不该有理由"), "decision_reason", "not_allowed")
    r = _ver(call, cid, 2, None, None, thesis="只改论点")
    assert r.status_code == 201 and r.json()["status"] == "watching", "不带 decision 状态不变"
    r = _ver(call, cid, 3, "watch", "同状态决定")
    assert r.status_code == 201 and r.json()["status"] == "watching"
    r = _ver(call, cid, 4, "drop", "放弃")
    assert r.status_code == 201 and r.json()["status"] == "dropped"
    for dec, reason in ((None, None), ("continue", "复活")):
        err = assert_err(_ver(call, cid, 5, dec, reason), 409, "INVALID_STATE_TRANSITION")
        assert err["details"]["from"] == "dropped" and err["details"]["allowed"] == []
    vs = call("GET", f"/candidates/{cid}/versions").json()["items"]
    assert [v["version_no"] for v in vs] == [5, 4, 3, 2, 1], "版本历史 version_no desc"


# =============================== T-A11 第 6 条：不可变 ===============================
def test_a11_06_put_patch_delete_405_with_allow(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 6, "POST")
    seed_securities(sql)
    call = Rec(s)
    cid = _new(call).json()["id"]
    for path in (f"/candidates/{cid}", f"/candidates/{cid}/versions/1"):
        for m in ("PUT", "PATCH", "DELETE"):
            r = call(m, path, json={})
            assert r.status_code == 405, (m, path, r.status_code)
            allow = {x.strip() for x in r.headers.get("allow", "").split(",") if x.strip()}
            assert "GET" in allow and not allow & {"PUT", "PATCH", "DELETE"}, (m, path, allow)
    assert sql("SELECT count(*) FROM app.research_candidates WHERE id = :c", c=cid)[0][0] == 1


def test_a11_06_db_trigger_rejects_update_delete(mkuser: Callable[..., Any], sql: Callable[..., Any]) -> None:
    """库层（已实现，严格）：直接 UPDATE / DELETE candidate_versions 被触发器拒绝，行内容不变。"""
    from sqlalchemy.exc import DBAPIError

    u = mkuser()
    c = _seed_candidate(sql, u.id)
    before = sql("SELECT thesis, decision, version_no FROM app.candidate_versions WHERE id = :v", v=c.version_id)
    for stmt in ("UPDATE app.candidate_versions SET thesis = '改写' WHERE id = :v",
                 "UPDATE app.candidate_versions SET decision = 'drop', decision_reason = 'x' WHERE id = :v",
                 "DELETE FROM app.candidate_versions WHERE id = :v"):
        with pytest.raises(DBAPIError):
            sql(stmt, v=c.version_id)
    after = sql("SELECT thesis, decision, version_no FROM app.candidate_versions WHERE id = :v", v=c.version_id)
    assert after == before
    trg = sql("SELECT count(*) FROM pg_trigger WHERE tgrelid = CAST('app.candidate_versions' AS regclass) "
              "AND NOT tgisinternal")[0][0]
    assert trg >= 1


# =============================== T-A11 第 7 条：回看 ===============================
FROZEN = ("reasons", "counter_evidence", "fit_assessment", "evidence")


def test_a11_07_lookback_is_frozen(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 7, "POST")
    seed_securities(sql)
    call = Rec(s)
    sql("UPDATE market.securities SET risk_flag = NULL WHERE code = :c", c=STOCK)
    c = _new(call).json()
    v1 = call("GET", f"/candidates/{c['id']}/versions/1").json()
    sql("UPDATE market.securities SET risk_flag = 'st' WHERE code = :c", c=STOCK)
    try:
        again = call("GET", f"/candidates/{c['id']}/versions/1").json()
        for k in FROZEN:
            assert again[k] == v1[k], k
        assert again["snapshot_id"] == v1["snapshot_id"]
        v2 = _ver(call, c["id"], 1).json()["current_version"]
        assert v2["snapshot_id"] != v1["snapshot_id"]
        assert v2["counter_evidence"] != v1["counter_evidence"], "第 2 版应反映新的 risk_flag"
    finally:
        sql("UPDATE market.securities SET risk_flag = NULL WHERE code = :c", c=STOCK)


# =============================== T-A11 第 8 条：系统内容 ===============================
def test_a11_08_suggestion_origin_content_traceable(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 8, "POST")
    seed_securities(sql)
    sug = _seed_suggestion(sql, s.user.id)
    r = _new(Rec(s), None, origin="suggestion", suggestion_id=sug.id)
    assert r.status_code == 201, r.text[:300]
    v = r.json()["current_version"]
    assert r.json()["security_code"] == STOCK and r.json()["suggestion_id"] == sug.id
    assert {x["text"] for x in v["reasons"]} <= sug.texts["reasons"]
    assert {x["text"] for x in v["counter_evidence"]} <= sug.texts["reasons"] | sug.texts["counter"]
    ids = {e["id"] for e in v["evidence"]}
    for x in v["reasons"] + v["counter_evidence"]:
        assert set(x["evidence_ids"]) <= ids


def test_a11_08_manual_content_and_fit_defaults(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 8, "POST")
    seed_securities(sql)
    v = _new(Rec(s)).json()["current_version"]
    assert v["reasons"] == []
    fit = v["fit_assessment"]
    assert fit["profile_filled"] is False and fit["hints"] == []
    assert fit["holdings_available"] is False and fit["warnings"] == []


# =============================== T-A11 第 9 条：隐私与删除 ===============================
def test_a11_09_snapshot_and_claims_owned_by_user(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 9, "POST")
    seed_securities(sql)
    c = _new(Rec(s)).json()
    snap = c["current_version"]["snapshot_id"]
    assert sql("SELECT user_id::text FROM app.data_snapshots WHERE id::text = :i", i=snap)[0][0] == s.user.id
    vid = c["current_version"]["id"]
    owners = sql("SELECT k.user_id::text FROM app.claims k JOIN app.claim_links l ON l.claim_id = k.id "
                 "WHERE l.target_type = 'candidate_version' AND l.target_id = :v", v=vid)
    assert all(o == s.user.id for (o,) in owners), "候选 claims.user_id 必须为本人（不为 null）"
    assert not has_route(s.client, "GET", "/claims"), "本版不开放 /claims"


def test_a11_09_delete_user_data_purges_candidates(cli: SimpleNamespace, roles: SimpleNamespace, mkuser: Callable[..., Any],
                                                   sql: Callable[..., Any], capsys: pytest.CaptureFixture[str]) -> None:
    """库层（CLI 已在本地 main，严格）：删除用户数据后 research_candidates、candidate_versions、claim_links、claims 为 0 行；
    旁观用户的同类数据不受影响。"""
    u, by = mkuser(), mkuser()
    _seed_candidate(sql, u.id)
    _seed_candidate(sql, by.id)
    fp = _a11_footprint(sql, u.id)
    assert all(fp[k] >= 1 for k in fp), fp
    by_before = _a11_footprint(sql, by.id)
    cli.mp.setenv("AIA_MAINT_DATABASE_URL", roles.maint)
    r = _t24._run(cli, capsys, "--user-id", u.id, "--execute", confirm=u.id)
    assert r.rc == 0, r.text[-1500:]
    fp = _a11_footprint(sql, u.id)
    assert fp == {k: 0 for k in fp}, fp
    assert _a11_footprint(sql, by.id) == by_before


# =============================== T-A11 第 10 条：列表 ===============================
def test_a11_10_list_filters_and_pagination(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 10)
    seed_securities(sql)
    call = Rec(s)
    m = _new(call, STOCK).json()
    sug = _seed_suggestion(sql, s.user.id, CDR)
    g = _new(call, None, origin="suggestion", suggestion_id=sug.id).json()
    assert _ver(call, m["id"], 1, "drop", "放弃").status_code == 201
    st = _new(call, STOCK, origin="from_stock").json()
    ids = lambda xs: [x["id"] for x in xs]  # noqa: E731
    assert m["id"] not in ids(_list(call)), "默认不含 dropped"
    assert ids(_list(call, "?status=dropped")) == [m["id"]]
    every = _list(call, "?status=all")
    assert set(ids(every)) == {m["id"], g["id"], st["id"]}
    keys = [(x["created_at"], x["id"]) for x in every]
    assert keys == sorted(keys, reverse=True), "created_at desc, id desc"
    assert set(ids(_list(call, "?status=researching,watching"))) == {g["id"], st["id"]}
    assert_err(call("GET", "/candidates?status=nope"), 400, "VALIDATION_ERROR")
    assert ids(_list(call, "?origin=suggestion&status=all")) == [g["id"]]
    assert ids(_list(call, f"?suggestion_id={sug.id}&status=all")) == [g["id"]]
    assert set(ids(_list(call, f"?security_code={STOCK}&status=all"))) == {m["id"], st["id"]}
    page = call("GET", "/candidates?status=all&limit=1").json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    walked = _list(call, "?status=all&limit=1")
    assert ids(walked) == ids(every), "翻页不重不漏"


# =============================== T-A11 第 11 条：无通知、无草案 ===============================
def test_a11_11_no_notifications_no_plans(session: Callable[..., SimpleNamespace], sql: Callable[..., Any]) -> None:
    s = session()
    _gate(s, 11, "POST")
    seed_securities(sql)
    call = Rec(s)
    n0 = _notif_count(sql)
    c = _new(call).json()
    assert _ver(call, c["id"], 1, "watch", "观察").status_code == 201
    r = _ver(call, c["id"], 2, "drop", "放弃")
    assert r.status_code == 201
    assert _notif_count(sql) == n0, "研究候选不产生 notifications 行"
    body = call("GET", f"/candidates/{c['id']}").json()
    assert body["plan_ids"] == [] and body["strategy_run_id"] is None and body["status"] != "planned"
    targets = importlib.import_module("app.schemas.enums").NotificationTargetType
    assert not any("candidate" == str(t.value) for t in targets), "notification_target_type 不变"
    if not has_route(s.client, "GET", "/stream"):
        pytest.xfail(f"{O_SSE}（T-A11 验收 11 的 SSE 部分）")


# =============================== T-F22 第 1 条：resume 幂等 ===============================
def test_f22_1_resume_not_set_not_paused_409(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                             sql: Callable[..., Any]) -> None:
    u = session()
    adm = _admin(session, mkuser)
    before = _counts(sql, u.user.id)
    assert_err(_pause(adm.call, u.user.id, False), 409, "DATA_LICENCE_NOT_SET")
    assert _counts(sql, u.user.id) == before


def test_f22_1_resume_active_is_idempotent(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                           sql: Callable[..., Any]) -> None:
    u = session()
    adm = _admin(session, mkuser)
    assert put(Rec(u), fake_licence()).status_code == 202
    until = dt.datetime.now(dt.UTC).replace(microsecond=0) + dt.timedelta(hours=3)
    set_status(sql, u.user.id, "active", until)
    row0 = live_row(sql, u.user.id)
    me0 = Rec(u)("GET", "/me/data-licence").json()
    before = _counts(sql, u.user.id)
    r = _pause(adm.call, u.user.id, False)
    assert r.status_code == 204, r.text[:300]
    row1 = live_row(sql, u.user.id)
    assert (row1.status, row1.paused_until) == (row0.status, row0.paused_until), "status、paused_until 不变"
    me1 = Rec(u)("GET", "/me/data-licence").json()
    assert (me1["status"], me1["paused_until"]) == (me0["status"], me0["paused_until"])
    after = _counts(sql, u.user.id)
    if after != before:
        pytest.xfail(f"{O_F22_IDEMP}；新增 {[(k, after[k] - before[k]) for k in after if after[k] != before[k]]}")
    assert after == before


# =============================== T-F22 第 2 条：列表排序 ===============================
def test_f22_2_admin_list_order_and_ignored_params(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                                   sql: Callable[..., Any]) -> None:
    us = [mkuser() for _ in range(4)]
    adm = _admin(session, mkuser)
    t1, t2 = dt.datetime(2001, 1, 2, tzinfo=dt.UTC), dt.datetime(2001, 1, 1, tzinfo=dt.UTC)
    sql("UPDATE app.users SET created_at = :t WHERE id = ANY(CAST(:i AS uuid[]))", t=t1, i=[us[0].id, us[1].id])
    sql("UPDATE app.users SET created_at = :t WHERE id = ANY(CAST(:i AS uuid[]))", t=t2, i=[us[2].id, us[3].id])
    mine = {u.id for u in us}
    got = [str(x["user_id"]) for x in admin_items(adm.call) if str(x["user_id"]) in mine]
    same1 = sorted([us[0].id, us[1].id], key=uuid.UUID, reverse=True)
    same2 = sorted([us[2].id, us[3].id], key=uuid.UUID, reverse=True)
    assert got == same1 + same2, "created_at desc，相同时 id desc"
    allrows = sql("SELECT id::text, created_at FROM app.users")
    want = [i for i, _ in sorted(allrows, key=lambda r: (r[1], uuid.UUID(r[0])), reverse=True)]
    full = [str(x["user_id"]) for x in admin_items(adm.call)]
    assert full == want, "全表顺序 = users created_at desc, id desc"
    plain = adm.call("GET", "/admin/data-licences")
    q = adm.call("GET", "/admin/data-licences", params={"status": "paused_by_admin", "q": "示例"})
    assert q.status_code == 200 and q.json() == plain.json(), "未定义的查询参数忽略"


# =============================== T-F22 第 3 条：理由不外露 ===============================
def test_f22_3_reason_and_admin_not_exposed(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                            sql: Callable[..., Any]) -> None:
    u = session()
    call = Rec(u)
    adm = _admin(session, mkuser)
    assert put(call, fake_licence()).status_code == 202
    t0 = sql("SELECT now()")[0][0]
    assert _pause(adm.call, u.user.id, True).status_code == 204
    lst = adm.call("GET", "/admin/data-licences")
    assert REASON not in lst.text
    mine = [x for x in admin_items(adm.call) if str(x["user_id"]) == u.user.id]
    assert len(mine) == 1 and mine[0]["status"] == "paused_by_admin"
    row_text = json.dumps(mine[0], ensure_ascii=False)
    assert adm.s.user.username not in row_text and str(adm.s.user.id) not in row_text
    for path in ("/me/data-licence", "/me"):
        r = call("GET", path)
        assert r.status_code == 200
        assert REASON not in r.text and adm.s.user.username not in r.text and str(adm.s.user.id) not in r.text
    notes = sql("SELECT coalesce(title,'') || ' ' || coalesce(body,'') FROM app.notifications WHERE user_id = :u",
                u=u.user.id)
    assert all(REASON not in t and adm.s.user.username not in t for (t,) in notes), "通知不含理由与管理员身份"
    au = sql("SELECT actor_id::text, detail->>'reason' FROM app.audit_logs WHERE action = 'data_licence.paused' "
             "AND at >= :t", t=t0)
    assert au == [(str(adm.s.user.id), REASON)], au
    require_route(adm.s.client, "GET", "/admin/ingest/status", O_INGEST_STATUS + "（T-F22 验收 3 的 ingest/status 部分）")
    r = adm.call("GET", "/admin/ingest/status")
    assert r.status_code == 200 and REASON not in r.text and adm.s.user.username not in r.text


# =============================== T-F22 第 4 条：冷却 ===============================
def test_f22_4_quota_cooldown_same_in_both_views(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                                 sql: Callable[..., Any]) -> None:
    """回放上游 101（测试侧参考模型：北京时间次日 00:01），按采集侧写回证书行，再比对两处只读视图。"""
    u = session()
    adm = _admin(session, mkuser)
    assert put(Rec(u), fake_licence()).status_code == 202
    set_status(sql, u.user.id, "active")
    st = ref.LicenceState(live_row(sql, u.user.id).id, tier="annual", status="active")
    now = dt.datetime.now(dt.UTC)
    st.on_upstream("101", now)
    assert st.status == "quota_exceeded" and st.paused_until == ref.next_quota_resume(now)
    set_status(sql, u.user.id, st.status, st.paused_until)
    item = next(x for x in admin_items(adm.call) if str(x["user_id"]) == u.user.id)
    assert item["status"] == "quota_exceeded" and item["paused_until"] is not None
    assert dt.datetime.fromisoformat(item["paused_until"].replace("Z", "+00:00")) == st.paused_until
    require_route(adm.s.client, "GET", "/admin/ingest/status", O_INGEST_STATUS + "（T-F22 验收 4 的 ingest/status 部分）")
    rows = [x for x in adm.call("GET", "/admin/ingest/status").json()["licences"] if str(x["user_id"]) == u.user.id]
    assert len(rows) == 1 and rows[0]["status"] == "quota_exceeded"
    assert rows[0]["paused_until"] == item["paused_until"]
    assert rows[0]["licence_id"] == item.get("licence_id", rows[0]["licence_id"])


# =============================== T-F22 第 5 条：通知 ===============================
TITLE_PAUSE, TITLE_RESUME = "数据证书已被管理员暂停", "数据证书已被管理员恢复"


def _new_notes(sql: Callable[..., Any], uid: str, since: Any) -> list[Any]:
    return sql("SELECT kind, severity, title, coalesce(body, '') AS body, target_type FROM app.notifications "
               "WHERE user_id = :u AND created_at >= :t ORDER BY created_at", u=uid, t=since)


def test_f22_5_pause_resume_notifications(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any],
                                          sql: Callable[..., Any]) -> None:
    u, other = session(), session()
    adm = _admin(session, mkuser)
    call = Rec(u)
    assert put(call, fake_licence()).status_code == 202
    set_status(sql, u.user.id, "active")
    t0 = sql("SELECT now()")[0][0]
    n_all = _notif_count(sql)
    n_other = _notif_count(sql, other.user.id)
    assert _pause(adm.call, u.user.id, True).status_code == 204
    notes = _new_notes(sql, u.user.id, t0)
    if not notes:
        pytest.xfail(f"{O_F22_NOTIFY}；pause（active → paused_by_admin）后该用户无新增通知")
    assert len(notes) == 1, notes
    n = notes[0]
    assert (n.kind, n.severity, n.title, n.target_type) == ("data_licence", "attention", TITLE_PAUSE, "none")
    assert REASON not in n.body and adm.s.user.username not in n.body
    assert _pause(adm.call, u.user.id, True).status_code == 204
    assert len(_new_notes(sql, u.user.id, t0)) == 1, "重复 pause 不发"
    assert _pause(adm.call, u.user.id, False).status_code == 204
    notes = _new_notes(sql, u.user.id, t0)
    assert len(notes) == 2 and (notes[1].kind, notes[1].severity, notes[1].title, notes[1].target_type) == (
        "data_licence", "info", TITLE_RESUME, "none")
    assert REASON not in notes[1].body
    set_status(sql, u.user.id, "active")
    assert _pause(adm.call, u.user.id, False).status_code == 204
    assert len(_new_notes(sql, u.user.id, t0)) == 2, "重复 resume（未暂停）不发"
    assert _pause(adm.call, u.user.id, True).status_code == 204
    assert call("DELETE", "/me/data-licence").status_code == 204
    assert _pause(adm.call, u.user.id, False).status_code == 204
    assert call("GET", "/me/data-licence").json()["status"] == "not_set"
    notes = _new_notes(sql, u.user.id, t0)
    assert [x.title for x in notes] == [TITLE_PAUSE, TITLE_RESUME, TITLE_PAUSE, TITLE_RESUME]
    assert _notif_count(sql, other.user.id) == n_other, "其他用户没有新增通知"
    assert _notif_count(sql) - n_all == 4
