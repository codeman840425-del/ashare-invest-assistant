"""plan v0.2.3 §6.1：``config/*.yaml`` 的键与默认值（“YAML 默认值 == 本节表格”，归测试）。

T-T01b 起对齐 plan/契约 v0.2.2（T-A02）：§6.1 由 5 个文件变为 6 个（新增 ``llm.yaml``），
``market_rules.yaml`` 增加 ``modeled_from`` / ``impact_cost.adv_basis`` / ``risk_warning`` 且第二段起始日改为
2023-04-10 并写全，``horizon_classifier.yaml`` 的特征统一为 ``f.*`` / ``sec.*`` / ``user.*`` / ``profile.*``、
``recompute."on"`` 增加 ``position_open_close``、``rules`` 给出全文（``rule_schema: 1``）。

四层比对：
1. 测试内快照 ``config_defaults/*.yaml``（plan §6.1 代码块原文）自身可解析、关键默认值正确、
   跨字段一致（不依赖文档、不依赖后端）；
2. 快照 == plan §6.1 代码块（需 v0.2.3 文档：``AIA_DOCS_DIR``，否则 skip）；
3. 快照能被后端 pydantic 模型接受（``app.config_files``）；后端模型未跟上 v0.2.3 的文件 → xfail，原因写明后端任务；
4. 仓库 ``config/*.yaml``（``AIA_CONFIG_DIR``）== 快照；T-A02 改动的文件不一致时 xfail 并写明负责任务，
   其余文件不一致直接失败。

T-T01d（T-A05，7c62f59，契约 #22）：§6.1 由 6 个文件变为 8 个（新增 ``imports.yaml``、``auth.yaml``）；
交割单上传上限的键路径改为 ``imports.max_file_bytes`` 等（``Settings.business.imports.*``），
T-B02a 暂放的 ``ingest.imports.*`` 作废，``ingest.yaml`` 不得再有 ``imports`` 段。
契约 v0.2.4（35f4880）：``auth.yaml`` 去掉 ``consents.doc_versions``（改由 ``legal_documents`` 表），
新增 ``admin.same_ip_highlight_threshold``；快照按 35f4880 的 plan §6.1 原文。
契约 v0.2.5（T-A06 bd33f83）：不做同意流程（``auth.yaml`` 仍无 consents 段）；``horizon_classifier.yaml`` 升到
``version_no: 3`` / ``classifier_version: "1.2.0"``，画像类 requires 改 ``mode: hint``，快照按 bd33f83 的 plan §6.1 原文；
docs 仍为 v0.2.4 时快照比对 xfail（运维推送 bd33f83）。
契约 v0.2.6（T-A07 308afd3）：``ingest.yaml`` 的 ``budget.*`` 改为每证书默认值，新增 ``licences``（档位每分钟上限、
DRR、熔断、ip_limited 升级、额度恢复时刻）与 ``data_sharing``（``per_licence``、``allow_cross_licence_fallback: false``）；
快照按 308afd3 的 plan §6.1 原文；仓库文件与后端模型未跟上 → xfail（后端 T-B04a 扩展）。

YAML 一律按 1.2 布尔规则读取（只认 true/false），与后端 ``config_files`` 一致；plan 已把 ``"on"`` 加引号。
"""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit]

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE / "config_defaults"
NAMES = ("realtime", "ingest", "market_rules", "risk_controls", "horizon_classifier", "llm", "imports", "auth", "securities")
#: T-A05 新增的文件（plan 7c62f59；origin/main 的 plan 尚无时 xfail，待运维推送）
T_A05_FILES = ("imports", "auth")
#: plan v0.2.7（T-A08 fa6d55d）新增的文件；所用 docs 尚无时 xfail（origin/main 仍为 v0.2.6，待运维推送）
V027_FILES = ("securities",)
V027_DOCS_PENDING = "plan §6.1 仍为 v0.2.6：架构师 T-A08 fa6d55d（v0.2.7，config/securities.yaml）未推到 origin（运维推送）"
#: nginx client_max_body_size 26m（deploy/nginx/nginx.conf；契约 #22 413 details.max_bytes）
NGINX_MAX_BODY = 26 * 1024 * 1024
REPO_ROOT = HERE.parents[2]
CONFIG_DIR = Path(os.environ.get("AIA_CONFIG_DIR") or REPO_ROOT / "config").resolve()  # 同 conftest.resolve_config_dir

#: T-A02 改动的文件 → 负责同步仓库文件与后端模型的任务
OWNER = {
    "market_rules": "后端 T-B36（交易规则模块：modeled_from / adv_basis / risk_warning，第二段 2023-04-10；v0.2.3 applies_to_boards 加 chinext、新增 limit_order_only_exchanges）",
    "horizon_classifier": "后端 T-B30（周期分类：f.* 特征、recompute 加 position_open_close、rules 全文；v0.2.5 version_no 3 / classifier_version 1.2.0 / 画像类 requires 为 mode: hint，T-A06 §3）",
    "llm": "后端 T-B25（LLM 网关：config/llm.yaml 与其模型）",
    "imports": "后端 T-B02a 跟进（T-A05：新建 config/imports.yaml 与模型，键路径 imports.*，删除 ingest.imports.*）",
    "ingest": "后端 T-B04a 扩展（T-A07 §5 / plan §6.1 v0.2.6：config/ingest.yaml 与模型加 licences、data_sharing 段）",
    "securities": "后端 T-B06（plan §6.1 v0.2.7：新建 config/securities.yaml 与模型 search.*、announcements.url_host_allowlist，由 api 读取）",
    "auth": "后端 T-B03 跟进（T-A05：新建 config/auth.yaml 与模型：password/password_hash/session/invite/admin；v0.2.4 无 consents 段）",
}
HORIZONS = ("intraday_t", "short", "swing", "long")
#: plan v0.2.5（T-A06 bd33f83）改动的 §6.1 代码块；docs 仍是 v0.2.4 时快照比对 xfail，待运维推送
V025_CHANGED = {"horizon_classifier": 3}
V025_DOCS_PENDING = "plan §6.1 仍为 v0.2.4：架构师 T-A06 bd33f83（v0.2.5，分类器 1.2.0）未推到 origin（运维推送）"
#: plan v0.2.6（T-A07 308afd3）新增的顶层段；所用 docs 尚无时快照比对 xfail
V026_ADDED = {"ingest": ("licences", "data_sharing")}
V026_DOCS_PENDING = "plan §6.1 仍为 v0.2.5：架构师 T-A07 308afd3（v0.2.6，每用户证书）不在所用 docs 中"
#: v0.2.9 内 T-B47 裁定（架构师 4532478，仅本地 main）新增的顶层段：plan 已加、快照已同步（T-T25）
V029_ADDED = {"realtime": ("admin_alerts",), "securities": ("master",)}  # securities.master：评审 d018fad M4（T-A04 4.6）
V029_DOCS_PENDING = "plan §6.1 尚无 realtime.admin_alerts：架构师 4532478（v0.2.9 内 T-B47 裁定）未推到 origin（运维推送）"
#: 上述新段在仓库 config/*.yaml 与后端 pydantic 模型（extra="forbid"）中尚未落地 → 仅这些键的差异 xfail
V029_BACKEND_PENDING = "后端 T-B47-x（R10）：config/realtime.yaml 与 app/config_files.py 尚无 admin_alerts（plan §6.1 v0.2.9 内裁定，问题 78）"
#: 按文件区分的文档 / 后端待办说明（未列出的文件用上面两条 realtime 的说明）
V029_DOCS_PENDING_BY = {"securities": "plan §6.1 securities.yaml 尚无 master 段：架构师 T-A04（4.6，本地 main）未推到 origin（运维推送）"}
V029_BACKEND_PENDING_BY = {"securities": "后端 T-B51（T-A04 4.6 证券主数据）：config/securities.yaml 与 app/config_files.py "
                                         "SecuritiesConfig 尚无 master 段（plan §6.1 v0.2.9 内，由 worker 读取）"}


#: T-R10（docs/strategies/market_rules_T-R10.md，后端 07b8d74 已并入 config/market_rules.yaml 与 config_files）新增键：
#: 快照已叠加（T-T25，取值与 T-R10 文档逐项核对一致）。架构师 46538a6（T-T25 裁定，契约 #32）已把 plan §6.1 同步
#: T-R10，plan 块解析后与快照完全相等 → market_rules 比对改为严格（不再按 TR10_PATH 放行差异）。
#: 只有所用 docs 早于 46538a6（plan 两段 lot 里一个 T-R10 键都没有、也没有 t0_round_trip，如 origin 0cb78ad）时
#: xfail，待运维推送；plan 一旦含任一 T-R10 键，任何差异都直接失败。
TR10_LOT_KEYS = ("odd_lot_sell_all", "star_odd_lot_threshold", "max_order_qty", "star_max_limit_order",
                 "star_max_market_order", "star_max_after_hours", "chinext_max_limit_order", "chinext_max_market_order")
TR10_PATH = re.compile(r"^segments\[\d+\]\.(lot\.(" + "|".join(TR10_LOT_KEYS) + r")|t0_round_trip)（")
TR10_DOCS_PENDING = "plan §6.1 尚无 T-R10 键：架构师 46538a6（T-T25 裁定，market_rules 同步 T-R10）未推到 origin（运维推送）"


def _plan_lacks_tr10(plan: dict) -> bool:
    """plan 的 market_rules 一个 T-R10 键都没有（所用 docs 早于 46538a6）。"""
    segs = plan.get("segments") or []
    return bool(segs) and all(not set(TR10_LOT_KEYS) & set(sg.get("lot") or {}) and "t0_round_trip" not in sg
                              for sg in segs)


#: T-O11 裁定 C5（架构师 e56462c，reports/T-O11-rulings.md）：SH5/SW2/SW3 的 unit 由 sign 改 pct、阈值 0（与
#: feature_catalog 一致）。快照已同步；所用 docs 早于 e56462c（这三项仍是 sign，如 origin 0cb78ad）时 xfail，待运维推送
C5_UNIT_PATH = re.compile(r"^rules\.horizons\.(short|swing)\.components\[\d+\]\.unit$")
C5_DOCS_PENDING = "plan §6.1 分类器 SH5/SW2/SW3 仍为 unit: sign：架构师 e56462c（T-O11 裁定 C5，改 pct）未推到 origin（运维推送）"


def _only_v029_keys(name: str, paths: list[str]) -> bool:
    keys = V029_ADDED.get(name, ())
    return bool(paths) and all(p.split(".", 1)[0].split("（", 1)[0] in keys for p in paths)


class _Yaml12Loader(yaml.SafeLoader):
    """布尔只认 true/false（YAML 1.2），避免裸 on/off/yes/no 被读成布尔。"""


_Yaml12Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def load12(text: str) -> Any:
    return yaml.load(text, Loader=_Yaml12Loader)  # noqa: S506 - SafeLoader 子类


def snap(name: str) -> dict[str, Any]:
    return load12((SNAP_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def plan_blocks(plan: str) -> dict[str, str]:
    sec = plan[plan.index("### 6.1 业务配置文件") : plan.index("## 7. 风险与合规")]
    return dict(re.findall(r"\*\*`config/([a-z_]+)\.yaml`\*\*[^\n]*\n```yaml\n(.*?)```", sec, re.S))


def diff_paths(a: Any, b: Any, path: str = "") -> list[str]:
    """两棵 YAML 树不同的键路径（只给路径，不输出取值）。"""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in a or k not in b:
                out.append(p + ("（仓库缺）" if k not in a else "（仓库多）"))
            else:
                out += diff_paths(a[k], b[k], p)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff_paths(u, v, f"{path}[{i}]")]
    return [] if a == b else [path or "<root>"]


def segment_for(mr: dict[str, Any], day: dt.date) -> dict[str, Any] | None:
    """参考实现（plan 2.13 + T-A02）：早于 modeled_from → None（“交易规则未建模”）；否则取 effective_from ≤ day 的最晚段。"""
    if day < dt.date.fromisoformat(mr["modeled_from"]):
        return None
    ok = [s for s in mr["segments"] if dt.date.fromisoformat(s["effective_from"]) <= day]
    return max(ok, key=lambda s: s["effective_from"]) if ok else None


# ---------------- 1. 快照自检 ----------------
@pytest.mark.parametrize("name", NAMES)
def test_snapshot_parses_with_schema_version(name):
    data = snap(name)
    assert isinstance(data, dict) and data["schema_version"] == 1


def test_key_defaults_realtime():
    d = snap("realtime")
    assert d["intervals"] == {"quote_interval_s": 15, "all_market_interval_s": 60, "pro_tier1_interval_s": 60,
                              "pro_tier2_interval_s": 300, "stale_threshold_s": None}
    assert d["boards"]["bse"] is False and d["boards"]["main"] is True
    assert (d["universe"]["tier1_cap"], d["universe"]["universe_hard_cap"]) == (1500, 4000)
    assert (d["watchlist"]["per_user_cap"], d["watchlist"]["focus_cap"]) == (100, 20)
    assert d["notify"]["cadence_default"] == "1min"
    assert d["notify"]["cadence_default"] in {"realtime", "1min", "3min", "5min"}
    assert (d["notify"]["sse_heartbeat_s"], d["notify"]["sse_replay_window_s"]) == (15, 600)
    assert d["intervals"]["quote_interval_s"] >= 5


def test_key_defaults_ingest_licences():
    """plan v0.2.6 §6.1 / 2.1B：档位默认每证书每分钟 = 官方一半；DRR；熔断与 ip_limited 参数；禁止跨证书回退。"""
    d = snap("ingest")
    lic = d["licences"]
    assert lic["tier_per_minute"] == {"diamond": 3000, "annual": 1500, "monthly": 500, "trial": 500, "free": 150, "other": 150}
    assert lic["tier_per_minute"]["diamond"] == d["budget"]["per_minute_budget"]
    assert (lic["per_licence_max_concurrency"], lic["global_max_concurrency"]) == (1, 2)
    assert (lic["cross_licence_scheduling"], lic["drr_quantum"]) == ("drr", 1)
    assert lic["breaker"] == {"consecutive_503": 5, "open_s": 300, "backoff_s": [1, 2, 4, 8, 16, 32, 60]}
    assert lic["ip_limited_pause_s"] == 120
    assert lic["ip_limited_escalate"] == {"count": 3, "window_s": 3600, "pause_s": 3600}
    assert lic["quota_resume_at"] == "00:01" and isinstance(lic["quota_resume_at"], str)
    assert lic["diamond_after_expiry_per_day"] == 20000
    assert lic["expiry_reminder_days"] == [30, 7, 1] and lic["verify_rate_limit_per_hour"] == 5
    assert lic["eod_scope"] == "user_universe"
    assert d["data_sharing"] == {"mode": "per_licence", "allow_cross_licence_fallback": False}


def test_key_defaults_ingest():
    d = snap("ingest")
    b = d["budget"]
    assert (b["per_minute_budget"], b["max_concurrency"]) == (3000, 1)
    assert sum(b["shares"].values()) <= b["per_minute_budget"]
    assert d["heartbeat"] == {"key": "ingest:heartbeat", "paused_key": "ingest:paused", "interval_s": 15,
                              "ttl_s": 600, "stale_after_s": 120}
    assert d["heartbeat"]["interval_s"] < d["heartbeat"]["stale_after_s"] < d["heartbeat"]["ttl_s"]
    assert d["leader"]["renew_every_s"] < d["leader"]["lease_s"]
    assert d["egress"]["check_on_start"] is True


def test_key_defaults_market_rules():
    d = snap("market_rules")
    assert d["modeled_from"] == "2023-04-10"
    first, second, third = d["segments"]
    assert first["effective_from"] == "2026-07-06" and second["effective_from"] == "2023-08-28"
    assert third["effective_from"] == "2023-04-10"
    assert first["price_limit_pct"] == {"main_board": 10, "main_board_st": 10, "chinext": 20, "star": 20, "bse": 30}
    assert first["sessions"] == {"call_auction": ["09:15", "09:25"], "morning": ["09:30", "11:30"],
                                 "afternoon": ["13:00", "14:57"], "closing_auction": ["14:57", "15:00"]}
    assert first["t_plus"] == 1 and first["lot"]["buy_lot"] == 100
    assert first["fees"]["stamp_duty_sell_pct"] == 0.05 and first["fees"]["commission_rate_default_pct"] is None
    ic = first["impact_cost"]
    assert ic["adv_basis"] == "amount" and ic["adv_window_days"] == 20  # T-A02：成交额口径
    assert [t["bp"] for t in ic["tiers"]] == [0, 5, 15, 30, 60]
    caps = [t["max_participation_pct"] for t in ic["tiers"]]
    assert caps[-1] is None and caps[:-1] == sorted(caps[:-1])
    rw = first["risk_warning"]
    # v0.2.3（T-A03）：50 万股上限扩到创业板；限价申报只作用于沪市
    assert rw == {"daily_buy_cap_shares": 500000, "limit_order_only": True,
                  "applies_to_boards": ["main_board", "chinext"], "limit_order_only_exchanges": ["SH"]}


def test_market_rules_second_segment_written_in_full():
    """正式三段写全：第二段仅ST比例变化，第三段仅印花税减半前税率变化。"""
    first, second, third = snap("market_rules")["segments"]
    assert set(first) == set(second)
    assert second["price_limit_pct"]["main_board_st"] == 5
    a = {k: v for k, v in first.items() if k != "effective_from"}
    b = {k: v for k, v in second.items() if k != "effective_from"}
    assert diff_paths(a, b) == ["price_limit_pct.main_board_st"]
    assert set(second) == set(third)
    c = {k: v for k, v in third.items() if k != "effective_from"}
    assert diff_paths(b, c) == ["fees.stamp_duty_sell_pct"]
    assert second["fees"]["stamp_duty_sell_pct"] == 0.05
    assert third["fees"]["stamp_duty_sell_pct"] == 0.1


@pytest.mark.parametrize(("day", "rate"), [
    ("2023-04-10", 0.1), ("2023-08-27", 0.1),
    ("2023-08-28", 0.05), ("2026-07-06", 0.05),
])
def test_market_rules_stamp_duty_plan_split(day, rate):
    segment = segment_for(snap("market_rules"), dt.date.fromisoformat(day))
    assert segment["fees"]["stamp_duty_sell_pct"] == rate


@pytest.mark.parametrize(("day", "st_pct"), [
    ("2026-07-03", 5),   # 周五：切换前最后一个交易日
    ("2026-07-06", 10),  # 周一：施行日
    ("2026-07-05", 5),   # 周日（非交易日）仍属旧段
    ("2023-04-10", 5),   # modeled_from 当天
    ("2023-04-09", None),  # 早于 modeled_from：交易规则未建模
])
def test_market_rules_st_switch_and_modeled_from(day, st_pct):
    """T-T19（T-A02 §6）：ST 5% → 10% 切换边界 07-03 / 07-06；modeled_from 之前返回“未建模”。"""
    seg = segment_for(snap("market_rules"), dt.date.fromisoformat(day))
    assert (None if seg is None else seg["price_limit_pct"]["main_board_st"]) == st_pct


def test_key_defaults_risk_controls():
    d = snap("risk_controls")
    assert d["rc2_position_cap"]["single_position_max_pct"] == 20
    assert d["rc3_total_exposure"]["regime_ranges"] == {"uptrend": [60, 90], "range": [40, 60], "downtrend": [0, 30]}
    for lo, hi in d["rc3_total_exposure"]["regime_ranges"].values():
        assert 0 <= lo <= hi <= 100
    assert (d["rc4_sector_concentration"]["sw_l1_max_pct"], d["rc4_sector_concentration"]["concept_max_pct"]) == (40, 50)
    assert d["rc5_loss_streak_drawdown"]["closed_loss_streak"] == 3
    assert d["executability"]["cooling_off_after_stop"] == {"enabled": False, "days": 3}
    assert d["executability"]["low_confidence_threshold"] == 0.4
    assert set(k for k in d if k.startswith("rc")) == {
        "rc1_stop_take", "rc2_position_cap", "rc3_total_exposure", "rc4_sector_concentration",
        "rc5_loss_streak_drawdown", "rc6_plan_violation"}


def test_key_defaults_horizon_classifier():
    d = snap("horizon_classifier")
    # v0.2.3：version_no 2 / 1.1.0（SH0C）；v0.2.5（T-A06）：画像类规则改 mode: hint → version_no 3 / 1.2.0
    assert (d["version_no"], d["classifier_version"], d["suitable_threshold"], d["reasons_per_horizon"]) == (3, "1.2.0", 60, [2, 4])
    assert re.fullmatch(r"\d+\.\d+\.\d+", d["classifier_version"])
    assert d["recompute"]["on"] == ["import_confirm", "watchlist_add", "weekly", "position_open_close"]
    assert True not in d["recompute"], "YAML 1.1 把裸 on 读成 true：plan 要求加引号"
    feats = d["features"]
    assert len(feats) == len(set(feats)) == 24
    assert all(re.fullmatch(r"(f|sec|user|profile)\.[a-z][a-z0-9_]*", f) for f in feats), feats
    r = d["rules"]
    assert r["rule_schema"] == 1 and r["calibration"] == "initial_values"
    assert r["data_missing_cap"]["cap"] < d["suitable_threshold"]
    assert sorted(r["tie_order"]) == sorted(HORIZONS) and set(r["horizons"]) == set(HORIZONS)


def _rule_inputs(rules: dict[str, Any]) -> list[str]:
    items = list(rules["gates"])
    for h in rules["horizons"].values():
        items += h["requires"] + h["components"]
    return [i["input"] for i in items]


def test_horizon_rules_reference_declared_features_only():
    d = snap("horizon_classifier")
    assert set(_rule_inputs(d["rules"])) <= set(d["features"])


def test_horizon_rules_ids_unique_and_caps_below_threshold():
    d = snap("horizon_classifier")
    r = d["rules"]
    ids = [g["id"] for g in r["gates"]] + [i["id"] for h in r["horizons"].values() for i in h["requires"] + h["components"]]
    assert len(ids) == len(set(ids))
    for g in r["gates"]:
        assert ("score" in g) != ("cap" in g)
        assert g.get("cap", 0) < d["suitable_threshold"] and g.get("score", 0) == 0
        assert g["horizons"] == "all" or set(g["horizons"]) <= set(HORIZONS)
    for h in r["horizons"].values():
        for q in h["requires"]:
            assert q.get("else_score", 0) == 0 and q.get("else_cap", 0) < d["suitable_threshold"]
            # v0.2.5：mode ∈ {cap(默认), hint}；hint 不得带 else_cap/else_score，cap 必须恰有其一
            if q.get("mode", "cap") == "hint":
                assert "else_cap" not in q and "else_score" not in q and q["input"].startswith("profile."), q["id"]
            else:
                assert q.get("mode", "cap") == "cap" and ("else_cap" in q) != ("else_score" in q), q["id"]


@pytest.mark.parametrize("horizon", HORIZONS)
def test_horizon_component_max_points_sum_to_100(horizon):
    """每个周期 components 的满分（每条取最高档）合计 100：分数为 0–100 的 int（契约 v0.2.2 scores）。"""
    comps = snap("horizon_classifier")["rules"]["horizons"][horizon]["components"]
    assert sum(max(b["pts"] for b in c["bands"]) for c in comps) == 100


def test_key_defaults_llm():
    d = snap("llm")
    ds = d["providers"]["deepseek"]
    assert ds["kind"] == "openai_compatible"
    assert ds["base_url"].startswith("https://")
    assert ds["base_url"].split("://", 1)[1].split("/")[0] in ds["allowed_hosts"]
    # 只写环境变量名，不写值（T-A02 / 契约 v0.2.1：api_key_source）
    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", ds["api_key_env"])
    assert not any(re.search(r"(?i)(api_?key|secret|token|password)$", k) for k in ds if k != "api_key_env")
    assert {t["model"] for t in d["tasks"].values()} <= set(d["models"])
    assert all(m["provider"] in d["providers"] for m in d["models"].values())
    retry = d["gateway"]["retry"]
    assert retry["max_retries"] == 2 and not set(retry["retry_on_status"]) & set(retry["no_retry_status"])
    assert d["budget"]["daily_budget_cny"] is None


def test_key_defaults_imports():
    """T-A05 / 契约 #22：上传上限键在 imports.yaml 顶层（imports.max_file_bytes），不在 ingest.yaml。"""
    d = snap("imports")
    assert (d["max_file_bytes"], d["max_files_per_upload"], d["max_request_bytes"]) == (5 * 1024 * 1024, 5, NGINX_MAX_BODY)
    assert d["max_request_bytes"] > d["max_file_bytes"] * d["max_files_per_upload"]
    assert (d["max_rows_per_file"], d["allowed_extensions"], d["raw_file_retention_days"]) == (50000, [".txt", ".csv"], 365)
    assert all(e == e.lower() and e.startswith(".") for e in d["allowed_extensions"])
    assert not [k for k in d if k.endswith(("_path", "_dir", "_env"))], "存储路径只来自环境变量，YAML 不设路径键"


def test_ingest_snapshot_has_no_imports_section():
    """T-B02a 暂放的 ingest.imports.* 作废（ingest.yaml 只由 ingest 进程读取）。"""
    d = snap("ingest")
    assert "imports" not in d and "max_file_bytes" not in str(d)


def test_key_defaults_auth():
    d = snap("auth")
    assert d["password"] == {"min_len": 10, "max_len": 128}
    ph = d["password_hash"]
    assert (ph["memory_kib"], ph["time_cost"], ph["parallelism"]) == (65536, 3, 1)
    assert ph["memory_kib"] >= 19456 and ph["time_cost"] >= 2 and ph["hash_len"] >= 16 and ph["salt_len"] >= 16
    se = d["session"]
    assert se == {"idle_ttl_s": 7 * 86400, "absolute_ttl_s": 30 * 86400, "remember_me": False}
    assert se["absolute_ttl_s"] >= se["idle_ttl_s"]
    inv = d["invite"]
    assert (inv["code_bytes"], inv["default_ttl_h"], inv["max_ttl_h"], inv["max_uses"]) == (16, 168, 720, 1)
    assert inv["default_ttl_h"] <= inv["max_ttl_h"]
    # 契约 v0.2.4 #3：auth.yaml 删除 consents 段（v0.2.5 同意流程整体作废）；新增审核提示阈值
    assert "consents" not in d and "doc_versions" not in str(d)
    assert d["admin"] == {"same_ip_highlight_threshold": 3}
    keys = [p for p in diff_paths(d, {}) if re.search(r"(?i)(secret|master_key|api_key|pepper)", p)]
    assert keys == [], "auth.yaml 不放密钥（APP_MASTER_KEY 只来自环境变量）"


def test_backend_upload_limit_key_path(backend, clean_env):
    """契约 #22：后端读 ``Settings.business.imports.max_file_bytes``；仍在 ``ingest.imports`` 下 → xfail（T-B02a 跟进）。"""
    business = backend.config.Settings().business
    imports = getattr(business, "imports", None)
    ingest_imports = getattr(getattr(business, "ingest", None), "imports", None)
    if imports is None and ingest_imports is not None:
        pytest.xfail(OWNER["imports"] + "；当前后端仍为 business.ingest.imports.*")
    if imports is None:
        pytest.skip("后端没有上传上限配置（T-B02a 未落地）")
    want = snap("imports")
    assert (imports.max_file_bytes, imports.max_files_per_upload, imports.max_request_bytes) == (
        want["max_file_bytes"], want["max_files_per_upload"], want["max_request_bytes"])
    assert ingest_imports is None, "ingest.imports.* 应删除"


def test_snapshot_matches_backend_settings_defaults(backend, clean_env):
    """ingest.yaml 的心跳键名/阈值与后端 Settings 默认值一致（契约 §7.10、plan §6.1）。"""
    s = backend.config.Settings()
    hb = snap("ingest")["heartbeat"]
    assert (s.ingest_heartbeat_key, s.ingest_paused_key, s.ingest_stale_after_s) == (hb["key"], hb["paused_key"], hb["stale_after_s"])


# ---------------- 2. 快照 == plan §6.1 ----------------
def _t_a05_missing(blocks: dict[str, str]) -> list[str]:
    return [n for n in T_A05_FILES if n not in blocks]


def test_plan_6_1_lists_nine_files(docs_dir):
    """白名单：T-A05 8 个文件，v0.2.7（T-A08）加 securities.yaml 共 9 个。docs 尚是更早版本 → xfail，待运维推送。"""
    blocks = plan_blocks((docs_dir / "plan.md").read_text(encoding="utf-8"))
    if set(blocks) == set(NAMES) - set(T_A05_FILES) - set(V027_FILES):
        pytest.xfail("plan §6.1 尚无 imports.yaml/auth.yaml：架构师 7c62f59 未推到 origin（运维推送）")
    if set(blocks) == set(NAMES) - set(V027_FILES):
        pytest.xfail(V027_DOCS_PENDING)
    assert set(blocks) == set(NAMES) and len(blocks) == 9


@pytest.mark.parametrize("name", NAMES)
def test_snapshot_equals_plan_block(docs_dir, name):
    blocks = plan_blocks((docs_dir / "plan.md").read_text(encoding="utf-8"))
    if name in _t_a05_missing(blocks):
        pytest.xfail(f"plan §6.1 尚无 {name}.yaml：架构师 7c62f59 未推到 origin（运维推送）")
    if name in V027_FILES and name not in blocks:
        pytest.xfail(V027_DOCS_PENDING)
    assert name in blocks, f"plan §6.1 已无 {name}.yaml"
    plan = load12(blocks[name])
    if name in V025_CHANGED and plan.get("version_no", 0) < V025_CHANGED[name] and snap(name)["version_no"] == V025_CHANGED[name]:
        pytest.xfail(V025_DOCS_PENDING)
    if name in V026_ADDED and not set(V026_ADDED[name]) & set(plan) and set(V026_ADDED[name]) <= set(snap(name)):
        pytest.xfail(V026_DOCS_PENDING)
    if name in V029_ADDED and not set(V029_ADDED[name]) & set(plan) and set(V029_ADDED[name]) <= set(snap(name)):
        pytest.xfail(V029_DOCS_PENDING_BY.get(name, V029_DOCS_PENDING))
    if name == "horizon_classifier" and plan != snap(name):
        d = diff_paths(plan, snap(name))
        if d and all(C5_UNIT_PATH.match(p) for p in d) and "unit: sign" in blocks[name]:
            pytest.xfail(C5_DOCS_PENDING)
    if name == "market_rules" and plan != snap(name) and _plan_lacks_tr10(plan):
        d = diff_paths(plan, snap(name))
        if d and all(TR10_PATH.match(p) for p in d):
            pytest.xfail(TR10_DOCS_PENDING)
    assert plan == snap(name), f"plan §6.1 的 {name}.yaml 已变，请同步快照"


# ---------------- 3. 后端模型接受 plan v0.2.3 快照 ----------------
def _models(cfgtools):
    names = cfgtools.business_files()
    if not names:
        pytest.skip("后端没有 app.config_files（plan §6.1 的 pydantic 模型未落地：T-B02）")
    import importlib  # noqa: PLC0415

    mod = importlib.import_module("app.config_files")
    return names, mod.BusinessConfig.model_fields


def test_backend_business_files_equal_plan_6_1(cfgtools):
    names, _ = _models(cfgtools)
    missing, extra = sorted(set(NAMES) - set(names)), sorted(set(names) - set(NAMES))
    if missing and not extra and set(missing) <= set(OWNER):
        pytest.xfail("后端 BUSINESS_FILES 缺 " + "、".join(missing) + "：" + "；".join(OWNER[m] for m in missing))
    assert (missing, extra) == ([], [])


@pytest.mark.parametrize("name", NAMES)
def test_backend_model_accepts_plan_snapshot(cfgtools, name):
    names, fields = _models(cfgtools)
    if name not in names:
        pytest.xfail(f"后端没有 {name}.yaml 的模型：{OWNER.get(name, 'T-B02')}")
    model = fields[name].annotation
    try:
        model.model_validate(snap(name))
    except Exception as exc:  # pydantic.ValidationError
        errs = getattr(exc, "errors", None)
        if callable(errs) and _only_v029_keys(name, [".".join(map(str, e["loc"])) for e in errs()]):
            pytest.xfail(V029_BACKEND_PENDING_BY.get(name, V029_BACKEND_PENDING))
        if name in OWNER:
            locs = sorted({".".join(map(str, e["loc"])) for e in getattr(exc, "errors", list)()})[:8]
            pytest.xfail(f"后端模型拒绝 plan §6.1 快照的 {name}.yaml（{locs}）：{OWNER[name]}")
        raise


# ---------------- 4. 仓库 config/*.yaml == 快照 ----------------
def _repo_file(name: str) -> Path:
    for ext in (".yaml", ".yml"):
        p = CONFIG_DIR / f"{name}{ext}"
        if p.is_file():
            return p
    if name in OWNER and any((CONFIG_DIR / f"{n}.yaml").is_file() for n in NAMES):
        pytest.xfail(f"{CONFIG_DIR.name}/{name}.yaml 未创建（plan §6.1）：{OWNER[name]}")
    pytest.skip(f"{CONFIG_DIR}/{name}.yaml 尚未创建（依赖 T-B01 后续 / T-B02：plan §6.1 文件由后端创建）")


@pytest.mark.parametrize("name", NAMES)
def test_repo_yaml_equals_plan_defaults(name):
    got = load12(_repo_file(name).read_text(encoding="utf-8"))
    diffs = diff_paths(got, snap(name))
    if _only_v029_keys(name, diffs):
        pytest.xfail(V029_BACKEND_PENDING_BY.get(name, V029_BACKEND_PENDING))
    if diffs and name in OWNER:
        pytest.xfail(f"仓库 config/{name}.yaml 与 plan §6.1 快照不一致 {diffs[:8]}：{OWNER[name]}")
    assert diffs == []


def test_repo_yaml_loads_in_settings(backend, cfgtools, clean_env, monkeypatch):
    present = [n for n in NAMES if (CONFIG_DIR / f"{n}.yaml").is_file()]
    if not present:
        pytest.skip(f"{CONFIG_DIR} 下没有 plan §6.1 的 yaml（依赖 T-B01 后续 / T-B02）")
    monkeypatch.setenv("CONFIG_DIR", str(CONFIG_DIR))
    business = cfgtools.business_dict(backend.config.Settings())
    assert set(cfgtools.business_files() or present) <= set(business)
