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
NAMES = ("realtime", "ingest", "market_rules", "risk_controls", "horizon_classifier", "llm")
REPO_ROOT = HERE.parents[2]
CONFIG_DIR = Path(os.environ.get("AIA_CONFIG_DIR", REPO_ROOT / "config")).resolve()

#: T-A02 改动的文件 → 负责同步仓库文件与后端模型的任务
OWNER = {
    "market_rules": "后端 T-B36（交易规则模块：modeled_from / adv_basis / risk_warning，第二段 2023-04-10；v0.2.3 applies_to_boards 加 chinext、新增 limit_order_only_exchanges）",
    "horizon_classifier": "后端 T-B30（周期分类：f.* 特征、recompute 加 position_open_close、rules 全文；v0.2.3 version_no 2 / classifier_version 1.1.0 / SH0C）",
    "llm": "后端 T-B25（LLM 网关：config/llm.yaml 与其模型）",
}
HORIZONS = ("intraday_t", "short", "swing", "long")


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
    first, second = d["segments"]
    assert first["effective_from"] == "2026-07-06" and second["effective_from"] == "2023-04-10"
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
    """第二段“除 main_board_st: 5 外与上一段相同（文件中写全，不做继承）”。"""
    first, second = snap("market_rules")["segments"]
    assert set(first) == set(second)
    assert second["price_limit_pct"]["main_board_st"] == 5
    a = {k: v for k, v in first.items() if k != "effective_from"}
    b = {k: v for k, v in second.items() if k != "effective_from"}
    assert diff_paths(a, b) == ["price_limit_pct.main_board_st"]


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
    # v0.2.3（T-A03，问题 37 方案 A）：新增 SH0C 发新版本 version_no 2 / classifier_version 1.1.0
    assert (d["version_no"], d["classifier_version"], d["suitable_threshold"], d["reasons_per_horizon"]) == (2, "1.1.0", 60, [2, 4])
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


def test_snapshot_matches_backend_settings_defaults(backend, clean_env):
    """ingest.yaml 的心跳键名/阈值与后端 Settings 默认值一致（契约 §7.10、plan §6.1）。"""
    s = backend.config.Settings()
    hb = snap("ingest")["heartbeat"]
    assert (s.ingest_heartbeat_key, s.ingest_paused_key, s.ingest_stale_after_s) == (hb["key"], hb["paused_key"], hb["stale_after_s"])


# ---------------- 2. 快照 == plan §6.1 ----------------
def test_plan_6_1_lists_six_files(docs_dir):
    blocks = plan_blocks((docs_dir / "plan.md").read_text(encoding="utf-8"))
    assert set(blocks) == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_snapshot_equals_plan_block(docs_dir, name):
    blocks = plan_blocks((docs_dir / "plan.md").read_text(encoding="utf-8"))
    assert name in blocks, f"plan §6.1 已无 {name}.yaml"
    assert load12(blocks[name]) == snap(name), f"plan §6.1 的 {name}.yaml 已变，请同步快照"


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
        if name in OWNER:
            locs = sorted({".".join(map(str, e["loc"])) for e in getattr(exc, "errors", list)()})[:8]
            pytest.xfail(f"后端模型拒绝 plan v0.2.3 的 {name}.yaml（{locs}）：{OWNER[name]}")
        raise


# ---------------- 4. 仓库 config/*.yaml == 快照 ----------------
def _repo_file(name: str) -> Path:
    for ext in (".yaml", ".yml"):
        p = CONFIG_DIR / f"{name}{ext}"
        if p.is_file():
            return p
    if name in OWNER and any((CONFIG_DIR / f"{n}.yaml").is_file() for n in NAMES):
        pytest.xfail(f"{CONFIG_DIR.name}/{name}.yaml 未创建（plan v0.2.3 §6.1）：{OWNER[name]}")
    pytest.skip(f"{CONFIG_DIR}/{name}.yaml 尚未创建（依赖 T-B01 后续 / T-B02：plan §6.1 文件由后端创建）")


@pytest.mark.parametrize("name", NAMES)
def test_repo_yaml_equals_plan_defaults(name):
    got = load12(_repo_file(name).read_text(encoding="utf-8"))
    diffs = diff_paths(got, snap(name))
    if diffs and name in OWNER:
        pytest.xfail(f"仓库 config/{name}.yaml 与 plan v0.2.3 不一致 {diffs[:8]}：{OWNER[name]}")
    assert diffs == []


def test_repo_yaml_loads_in_settings(backend, cfgtools, clean_env, monkeypatch):
    present = [n for n in NAMES if (CONFIG_DIR / f"{n}.yaml").is_file()]
    if not present:
        pytest.skip(f"{CONFIG_DIR} 下没有 plan §6.1 的 yaml（依赖 T-B01 后续 / T-B02）")
    monkeypatch.setenv("CONFIG_DIR", str(CONFIG_DIR))
    business = cfgtools.business_dict(backend.config.Settings())
    assert set(cfgtools.business_files() or present) <= set(business)
