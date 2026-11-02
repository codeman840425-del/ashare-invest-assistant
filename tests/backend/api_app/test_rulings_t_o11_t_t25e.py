"""T-T25 追加（T-O11 裁定，架构师 2026-11-01，reports/T-O11-rulings.md“测试员”①–③）。

- ① market_rules / realtime 快照与 alembic head（0016）：见 ``test_config_yaml_defaults.py``、``test_auth_t_b03.py``；
- ② T-T16：候选（purpose='candidate'）数据快照必须带 user_id、属本人、跨用户不可见（裁定 D：CHECK 加入 candidate）；
- ③ ETF 在 ``t0_round_trip.data_source`` 为 null 或空串时一律 T+1（plan 2.13 新增行、契约 v0.2.8 #9；裁定 m④：
  ``fund_t_plus`` 须以 data_source 非空为闸门）。

门控：已实现部分严格断言；未实现部分 ``xfail(strict=False)``，写明 owner（后端）。
真实 PG/Redis 一次性临时库（T-T22/T-T23 夹具），进程内 TestClient；不联网、不调用麦蕊、不碰共享库。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tt25e_a11", _HERE / "test_contract_t_a11_t_f22.py")
_a11 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_a11)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)

authdb, sql, app_client, mkuser, session, make_settings = (
    _a11.authdb, _a11.sql, _a11.app_client, _a11.mkuser, _a11.session, _a11.make_settings)
Rec, assert_err, seed_securities = _a11.Rec, _a11.assert_err, _a11.seed_securities
_new, _ver, _list, _gate = _a11._new, _a11._ver, _a11._list, _a11._gate

pytestmark = [pytest.mark.integration, pytest.mark.contract]

REPO = Path(__file__).resolve().parents[3]
O_D_CAND = "后端（T-O11 裁定 D：新迁移把 candidate 加入“user_id 必填”CHECK，并在写入函数断言 user_id 非空）"
O_T1_GATE = "后端 T-B47-R10（T-O11 裁定 m④：fund_t_plus 须以 t0_round_trip.data_source 非空为闸门，未接入前 ETF 一律 T+1）"
O_LOTS = "后端 T-B47-R10（app.market_rules.lots / t0_round_trip：在本地 main 07b8d74，未推 origin）"


# =============================== ② T-T16：候选快照 user_id ===============================
def _cand_snaps(sql: Callable[..., Any], ids: list[str]) -> dict[str, tuple[str, str | None]]:
    rows = sql("SELECT id::text, purpose, user_id::text FROM app.data_snapshots WHERE id::text = ANY(:i)", i=ids)
    return {i: (p, u) for i, p, u in rows}


def _version_snaps(call: Rec, cid: str) -> list[str]:
    r = call("GET", f"/candidates/{cid}/versions")
    assert r.status_code == 200, r.text[:300]
    return [v["snapshot_id"] for v in r.json()["items"]]


def test_t16_candidate_snapshot_user_id_every_version(session: Callable[..., SimpleNamespace],
                                                     sql: Callable[..., Any]) -> None:
    """每个版本的快照：存在、purpose=candidate、user_id 非空且为本人；两个用户同一证券各自独立快照。"""
    a, b = session(), session()
    _gate(a, 9, "POST")
    seed_securities(sql)
    ca, cb = Rec(a), Rec(b)
    ra, rb = _new(ca), _new(cb)
    assert ra.status_code == 201 and rb.status_code == 201, (ra.text[:300], rb.text[:300])
    cid_a, cid_b = ra.json()["id"], rb.json()["id"]
    assert _ver(ca, cid_a, 1, decision="continue", reason="测试继续").status_code == 201
    snaps_a, snaps_b = _version_snaps(ca, cid_a), _version_snaps(cb, cid_b)
    assert len(snaps_a) == 2 and len(snaps_b) == 1
    assert all(snaps_a + snaps_b), "每个版本都必须带 snapshot_id"
    assert not set(snaps_a) & set(snaps_b), "不同用户不得共用快照行"
    got = _cand_snaps(sql, snaps_a + snaps_b)
    assert set(got) == set(snaps_a + snaps_b), "snapshot_id 必须指向已存在的 data_snapshots 行"
    for sid in snaps_a:
        assert got[sid] == ("candidate", a.user.id), sid
    for sid in snaps_b:
        assert got[sid] == ("candidate", b.user.id), sid
    n_null = sql("SELECT count(*) FROM app.data_snapshots WHERE purpose = 'candidate' AND user_id IS NULL")[0][0]
    assert n_null == 0, "candidate 快照不得有 user_id 为 null 的行"


def test_t16_candidate_snapshot_not_visible_across_users(session: Callable[..., SimpleNamespace],
                                                        sql: Callable[..., Any]) -> None:
    """B 的任何候选接口响应都不出现 A 的快照 id / 快照内容；直接按 A 的候选取版本 → 404（与不存在同形）。"""
    a, b = session(), session()
    _gate(a, 9, "POST")
    seed_securities(sql)
    ca, cb = Rec(a), Rec(b)
    cid_a = _new(ca).json()["id"]
    snap_a = _version_snaps(ca, cid_a)[0]
    items_a = sql("SELECT items::text FROM app.data_snapshots WHERE id::text = :i", i=snap_a)[0][0]
    cid_b = _new(cb).json()["id"]
    for path in (f"/candidates/{cid_a}/versions/1", f"/candidates/{cid_a}/versions", f"/candidates/{cid_a}"):
        assert_err(cb("GET", path), 404, "NOT_FOUND")
    seen = [json.dumps(_list(cb, q), ensure_ascii=False) for q in ("", "?status=all")]
    for path in (f"/candidates/{cid_b}", f"/candidates/{cid_b}/versions", f"/candidates/{cid_b}/versions/1"):
        r = cb("GET", path)
        assert r.status_code == 200, r.text[:300]
        seen.append(r.text)
    blob = "\n".join(seen)
    assert snap_a not in blob, "B 的响应里出现了 A 的 snapshot_id"
    assert cid_a not in blob
    # 快照内容按用户各自生成：B 的版本快照不是 A 那一行
    assert _version_snaps(cb, cid_b)[0] != snap_a
    assert items_a  # A 的快照有内容（非空 JSON），上面的“不出现”断言才有意义


@pytest.mark.xfail(strict=False, reason=f"{O_D_CAND}：purpose='candidate' 且 user_id 为 null 应被库级 CHECK 拒绝（23514）")
def test_t16_db_rejects_candidate_snapshot_without_user(sql: Callable[..., Any]) -> None:
    with pytest.raises(Exception) as ei:
        sql("INSERT INTO app.data_snapshots (purpose, items, hash, user_id) VALUES ('candidate', CAST('{}' AS jsonb), :h, NULL)",
            h="tt25e-null-user")
    orig = getattr(ei.value, "orig", ei.value)
    assert (getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)) == "23514"
    diag = getattr(orig, "diag", None)
    assert getattr(diag, "constraint_name", None) != "ck_data_snapshots_purpose"


@pytest.mark.xfail(strict=False, reason=f"{O_D_CAND}：research.content.write_snapshot(user_id=None) 应在应用层拒写")
def test_t16_writer_asserts_user_id(authdb: SimpleNamespace, sql: Callable[..., Any]) -> None:
    try:
        rc = importlib.import_module("app.research.content")
    except ImportError as exc:  # origin 上尚无 T-B10
        pytest.xfail(f"后端 T-B10（app.research.content 不存在：{exc.name}）")
    before = sql("SELECT count(*) FROM app.data_snapshots WHERE purpose = 'candidate' AND user_id IS NULL")[0][0]
    conn = authdb.engine.connect()
    tx = conn.begin()
    try:
        with pytest.raises(Exception):
            rc.write_snapshot(conn, None, {"tt25e": True})  # type: ignore[arg-type]
    finally:
        tx.rollback()
        conn.close()
    assert sql("SELECT count(*) FROM app.data_snapshots WHERE purpose = 'candidate' AND user_id IS NULL")[0][0] == before


# =============================== ③ ETF：data_source 为空一律 T+1 ===============================
def _lots() -> Any:
    try:
        return importlib.import_module("app.market_rules.lots")
    except ImportError:
        pytest.xfail(O_LOTS)


def _repo_segments(data_source: Any) -> list[Any]:
    """仓库 config/market_rules.yaml 的全部段（经后端 pydantic 模型校验），把 t0_round_trip.data_source 换成给定值。"""
    import yaml  # noqa: PLC0415

    cf = importlib.import_module("app.config_files")
    raw = yaml.safe_load((REPO / "config" / "market_rules.yaml").read_text(encoding="utf-8"))
    for seg in raw["segments"]:
        if "t0_round_trip" not in seg:
            pytest.xfail(O_LOTS + "：config/market_rules.yaml 无 t0_round_trip")
        seg["t0_round_trip"]["data_source"] = data_source
    cfg = cf.MarketRulesConfig.model_validate(raw)
    return list(cfg.segments)


#: 在 fund_categories 内的类别：data_source 接入后才可能为 T+0；未接入（null / ""）时必须 T+1
T0_CANDIDATES = [
    pytest.param({"etf_category": "bond"}, id="bond_etf"),
    pytest.param({"etf_category": "money"}, id="money_etf"),
    pytest.param({"etf_category": "gold"}, id="gold_etf"),
    pytest.param({"etf_category": "commodity_futures"}, id="commodity_futures_etf"),
    pytest.param({"etf_category": "cross_border", "constituents_t0": True}, id="cross_border_etf"),
    pytest.param({"is_cross_border": True, "constituents_t0": True, "is_lof": True}, id="cross_border_lof"),
]
#: 本来就是 T+1 的情形（不受闸门影响，严格断言）
T1_ANYWAY = [
    pytest.param({}, id="no_category"),
    pytest.param({"etf_category": "stock"}, id="stock_etf"),
    pytest.param({"etf_category": "other"}, id="other"),
    pytest.param({"etf_category": "cross_border", "constituents_t0": None}, id="cross_border_unknown_constituents"),
]


@pytest.mark.parametrize("data_source", [None, ""], ids=["null", "empty_string"])
@pytest.mark.parametrize("kw", T1_ANYWAY)
def test_etf_without_data_source_t_plus_1_baseline(data_source: Any, kw: dict[str, Any]) -> None:
    lots = _lots()
    for seg in _repo_segments(data_source):
        assert lots.fund_t_plus(seg, security_type="etf", **kw) == 1, (str(seg.effective_from), kw)


@pytest.mark.xfail(strict=False, reason=O_T1_GATE)
@pytest.mark.parametrize("data_source", [None, ""], ids=["null", "empty_string"])
@pytest.mark.parametrize("kw", T0_CANDIDATES)
def test_etf_without_data_source_always_t_plus_1(data_source: Any, kw: dict[str, Any]) -> None:
    """data_source 为 null / 空串：即使调用方传入 T+0 类别（债券/货币/黄金/商品期货/跨境 ETF、跨境 LOF），也必须返回 1。"""
    lots = _lots()
    for seg in _repo_segments(data_source):
        assert seg.t0_round_trip.data_source in (None, "")
        assert lots.fund_t_plus(seg, security_type="etf", **kw) == 1, (str(seg.effective_from), kw)


def test_etf_default_segment_none_is_t_plus_1() -> None:
    """未建模日期（seg=None）：ETF 一律 T+1（含传入 T+0 类别）。"""
    lots = _lots()
    assert lots.fund_t_plus(None, security_type="etf") == 1
    assert lots._DEFAULT_T0.data_source in (None, "")


def test_repo_config_data_source_not_connected() -> None:
    """仓库配置当前 data_source 未接入（null）：③ 的前提成立；接入后本用例提醒复核 ③ 的断言范围。"""
    _lots()
    import yaml  # noqa: PLC0415

    raw = yaml.safe_load((REPO / "config" / "market_rules.yaml").read_text(encoding="utf-8"))
    assert [s.get("t0_round_trip", {}).get("data_source") for s in raw["segments"]] == [None] * len(raw["segments"])
