"""T-B187（T-A209 M1）隔离草案：只测 schema 与旧 JSON 投影，不读库或行情。

出处简称：T-A209 指 reports/T-A209.md（团队报告），
与 docs/contracts/T-A209-market-wiring.md（#273@41b8898）同文；API 指
docs/api-contract.md。以 T-A209 §2、§3.2 为契约，来源口径仅参考 §3.1。
未验证 U1：指数/快照字段单位、批次一致性；未验证 U2：历史资格池。
未验证 U3：F25 正式阈值；未验证 U4：涨跌停字段。这里只验证合成结构，
不验证上述参数，不采集、不计算宽度、不选批、不运行 F25、不测试 HTTP/前端。
"""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from uuid import UUID

import pytest
from pydantic import ValidationError


pytestmark = pytest.mark.unit
REASON = (
    "T-B187 未落地；出处：T-A209 §2、§3.2（#273@41b8898）；"
    "API §7.3、§5.3、§1.1 A-12；reviews.py data_snapshots（purpose=report）"
)
SCOPE = "沪深股票口径"
SOURCE = "synthetic://tb187/market-snapshot-endpoint"
BEIJING = timezone(timedelta(hours=8))
NOW = datetime(2031, 1, 9, 11, 20, tzinfo=BEIJING)
SOURCE_TIME = datetime(2031, 1, 7, 14, 12, tzinfo=BEIJING)
FETCHED_TIME = datetime(2031, 1, 7, 14, 13, tzinfo=BEIJING)
SNAPSHOT_ID = "00000000-0000-4000-8000-000000000187"
USER_ID = "00000000-0000-4000-8000-000000000201"
LICENCE_ID = "00000000-0000-4000-8000-000000000202"
BATCH_ID = "00000000-0000-4000-8000-000000000203"
COUNTS = ("eligible", "observed", "trading", "suspended", "missing")


@pytest.fixture(autouse=True)
def deny_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """出处：本任务纯单元隔离约束；只安装拦截，不创建 socket 或连接 PG。"""

    def denied(*args, **kwargs):
        pytest.fail("T-B187 schema 测试禁止网络、socket 与数据库连接")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    for operation in ("connect", "connect_ex", "bind"):
        monkeypatch.setattr(socket.socket, operation, denied)


def _load(path: str, *, fields: tuple[str, ...] = ()):
    """出处：T-B187 实现约定；延迟查找，未落地时不造成模块级收集错误。"""
    module_name, _, name = path.rpartition(".")
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name or module_name.startswith(f"{exc.name}."):
            pytest.xfail(f"{REASON}；缺少 {module_name}")
        raise
    target = getattr(module, name, None)
    if target is None:
        pytest.xfail(f"{REASON}；缺少 {path}")
    missing = set(fields) - set(getattr(target, "model_fields", {}))
    if missing:
        pytest.xfail(f"{REASON}；{path} 缺字段 {sorted(missing)}")
    return target


def _basis(*, known: bool = False, mode: str = "intraday") -> dict:
    """出处：T-A209 §3.2；scope 是输出说明，source 是合成端点标签。"""
    payload = dict.fromkeys(("snapshot_id", "observed_date", "mode", *COUNTS, "source"))
    payload["scope"] = SCOPE
    if known:
        payload.update(
            snapshot_id=SNAPSHOT_ID,
            observed_date=SOURCE_TIME.date().isoformat(),
            mode=mode,
            eligible=9,
            observed=7,
            trading=5,
            suspended=2,
            missing=2,
            source=SOURCE,
        )
    return payload


def _parse(model, payload: dict):
    """出处：T-A209 §2、§3.2；合成 JSON 通过模型真实序列化边界。"""
    return model.model_validate_json(json.dumps(payload, ensure_ascii=False), strict=True)


def _overview(*, known: bool = False) -> dict:
    """出处：API §7.3；配置指数仅为合成夹具，不固定方案样例或清单。"""
    return {
        "trade_date": SOURCE_TIME.date().isoformat(),
        "session": "afternoon",
        "indices": [{
            "security_code": "999991.SH", "name": "合成配置指数甲",
            "price": "12.34" if known else None,
            "change_pct": "0.12" if known else None,
            "amount": "123.45" if known else None,
            "t": SOURCE_TIME.isoformat() if known else None,
        }],
        "breadth": None,
        "regime": None,
        "regime_position_range": None,
        "turnover_total": None,
        "data_status": "stale" if known else "unavailable",
        "data_as_of": SOURCE_TIME.isoformat() if known else None,
        "gaps": [{"key": "market.breadth", "reason": "no_source", "message": "合成缺口"}],
    }


def _daily_market(*, breadth: bool = True) -> dict:
    """出处：API §5.3；旧日报无 basis/DataStatusBlock，breadth 无 flat。"""
    return {
        "regime": None,
        "regime_position_range": None,
        "breadth": {"up": 2, "down": 1, "limit_up": 0, "limit_down": 0} if breadth else None,
        "summary": [{"text": "合成旧日报市场说明", "expr": None, "evidence_ids": []}],
    }


def _old_payload(kind: str) -> dict:
    """出处：API §7.3、§5.3；这些旧字段须在新模型中继续保留。"""
    if kind == "MarketOverview":
        return _overview()
    if kind == "Market":
        return _daily_market()
    payload = {"regime": None, "regime_position_range": None, "data_status": "unavailable"}
    if kind == "Account":
        payload.update(
            account_id=USER_ID, total_assets="100.00", cash_available="100.00",
            position_pct=None, pnl_day=None,
        )
    return payload


MODEL_PATHS = (
    "app.aggregates.models.MarketOverview",
    "app.aggregates.models.TodayMarket",
    "app.aggregates.models.Account",
    "app.reports.models.Market",
)


@pytest.mark.parametrize("path", MODEL_PATHS)
def test_legacy_shapes_still_parse(path: str) -> None:
    """出处：API §7.3、§5.3；正向证明当前旧形状可解析，不依赖新实现。"""
    payload = _old_payload(path.rsplit(".", 1)[1])
    output = _parse(_load(path), payload).model_dump(mode="json")
    for key, value in payload.items():
        assert output[key] == value  # 出处：API §7.3、§5.3，保留旧字段和值。


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize("mode", ["intraday", "close"])
def test_basis_known_values_and_open_source_label(mode: str) -> None:
    """出处：T-A209 §3.2；来源字符串不扩充 DataProvider 枚举。"""
    model = _load("app.aggregates.models.MarketBasis")
    providers = _load("app.schemas.enums.DataProvider")
    before = tuple(member.value for member in providers)
    payload = _basis(known=True, mode=mode)
    parsed = _parse(model, payload)
    assert parsed.snapshot_id == UUID(SNAPSHOT_ID)  # 出处：T-A209 §3.2，uuid 类型。
    assert parsed.observed_date == date(2031, 1, 7)  # 出处：T-A209 §3.2，观察日期。
    assert parsed.model_dump(mode="json") == payload  # 出处：T-A209 §3.2，全部 basis 字段。
    assert payload["missing"] == payload["eligible"] - payload["observed"]  # 出处：T-A209 §3.2。
    assert SOURCE not in before  # 出处：T-A209 §3.2，source 可为非 provider 的端点标签。
    assert tuple(member.value for member in providers) == before  # 出处：T-A209 §3.2，不扩枚举。


@pytest.mark.xfail(strict=True, reason=REASON)
def test_basis_all_unknown_fields_remain_explicit_null() -> None:
    """出处：T-A209 §2、§3.2；缺资格池时依赖计数未知，不补零或覆盖率。"""
    model = _load("app.aggregates.models.MarketBasis")
    output = json.loads(_parse(model, _basis()).model_dump_json())
    assert output == _basis()  # 出处：T-A209 §3.2，所有 nullable 字段保留 null。
    assert all(output[key] is None for key in COUNTS)  # 出处：T-A209 §3.2，资格池缺失。
    assert output["scope"] == SCOPE  # 出处：T-A209 §3.2，输出解释固定为沪深股票口径。


@pytest.mark.xfail(strict=True, reason=REASON)
def test_basis_without_eligibility_cannot_expose_dependent_counts() -> None:
    """出处：T-A209 §3.2；缺资格池时拒绝矛盾输入或把依赖计数归为未知。"""
    model = _load("app.aggregates.models.MarketBasis")
    payload = _basis(known=True)
    payload["eligible"] = None
    try:
        output = _parse(model, payload).model_dump(mode="json")
    except ValidationError:
        return  # 出处：T-A209 §3.2，允许 schema 直接拒绝缺资格池却含依赖计数的输入。
    assert all(output[key] is None for key in COUNTS)  # 出处：T-A209 §3.2，禁止输出虚构覆盖计数。


@pytest.mark.xfail(strict=True, reason=REASON)
def test_basis_confirmed_zero_is_not_unknown() -> None:
    """出处：T-A209 §2、§3.2；仅验证计数 schema，真实零与未知有区别。"""
    model = _load("app.aggregates.models.MarketBasis")
    payload = _basis(known=True)
    payload.update(dict.fromkeys(COUNTS, 0))
    output = _parse(model, payload).model_dump(mode="json")
    assert all(type(output[key]) is int and output[key] == 0 for key in COUNTS)  # 出处：T-A209 §3.2。


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize("field", COUNTS)
@pytest.mark.parametrize("value", [-1, 0.5, "2", True])
def test_basis_counts_require_nonnegative_integers(field: str, value: object) -> None:
    """出处：T-A209 §2、§3.2；数量家数是非负整数，不接受伪零或隐式类型替换。"""
    model = _load("app.aggregates.models.MarketBasis")
    payload = _basis(known=True)
    payload[field] = value
    with pytest.raises(ValidationError):  # 出处：T-A209 §2、§3.2，计数类型与非负约束。
        _parse(model, payload)


@pytest.mark.xfail(strict=True, reason=REASON)
def test_basis_rejects_inconsistent_missing() -> None:
    """出处：T-A209 §3.2；只检查 schema 关系，不实现资格过滤或宽度计算。"""
    model = _load("app.aggregates.models.MarketBasis")
    payload = _basis(known=True)
    payload["missing"] = 1
    with pytest.raises(ValidationError):  # 出处：T-A209 §3.2，三者皆有时 missing=eligible−observed。
        _parse(model, payload)


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize(("field", "value"), [
    ("snapshot_id", "synthetic-not-a-uuid"), ("observed_date", "2031-02-30"),
    ("mode", "synthetic-unsupported-mode"), ("scope", None), ("source", 123),
])
def test_basis_rejects_invalid_scalar_types(field: str, value: object) -> None:
    """出处：T-A209 §3.2；uuid/date、两个 mode、非空字符串 scope、可空字符串 source。"""
    model = _load("app.aggregates.models.MarketBasis")
    payload = _basis(known=True)
    payload[field] = value
    with pytest.raises(ValidationError):  # 出处：T-A209 §3.2，basis 字段类型。
        _parse(model, payload)


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize(("user_id", "licence_id"), [(None, None), (USER_ID, None), (USER_ID, LICENCE_ID)])
@pytest.mark.parametrize("timed", [False, True])
def test_internal_report_snapshot_serializes_nullable_identity_and_source(
    user_id: str | None, licence_id: str | None, timed: bool,
) -> None:
    """出处：T-A209 §3.2 内部增量；reviews.py data_snapshots（purpose=report）。

    本人/证书仅声明隔离键，不连接数据库、不证明读取授权。内部字段名为本草案
    给实现者的 schema 夹具约定；资格与 F25 只留证据槽，不验证 U1–U4 的业务事实。
    """
    model = _load("app.aggregates.models.MarketSnapshotRecord")
    payload = {
        "snapshot_id": SNAPSHOT_ID,
        "purpose": "report",
        "user_id": user_id,
        "licence_id": licence_id,
        "batch_id": BATCH_ID if timed else None,
        "source_as_of": SOURCE_TIME.isoformat() if timed else None,
        "fetched_at": FETCHED_TIME.isoformat() if timed else None,
        "basis": _basis(known=timed),
        "eligibility_evidence": [],
        "f25_evidence": [],
    }
    output = json.loads(_parse(model, payload).model_dump_json())
    for key, value in payload.items():
        assert output[key] == value  # 出处：T-A209 §3.2 内部增量；reviews.py data_snapshots。
    assert output["purpose"] == "report"  # 出处：reviews.py data_snapshots 的 report purpose。


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize("path", MODEL_PATHS)
def test_new_basis_is_shared_and_existing_fields_are_preserved(path: str) -> None:
    """出处：T-A209 §3.2；概览、今日、终端账户、日报市场使用同形 basis。"""
    kind = path.rsplit(".", 1)[1]
    fields = ("basis", "data_status", "data_as_of", "gaps") if kind == "Market" else ("basis",)
    model = _load(path, fields=fields)
    payload = _old_payload(kind)
    payload["basis"] = _basis(known=True)
    if kind == "Market":
        payload.update(data_status="unavailable", data_as_of=None, gaps=[])
    output = _parse(model, payload).model_dump(mode="json")
    for key, value in payload.items():
        assert output[key] == value  # 出处：T-A209 §3.2；API §7.3、§5.3，保留字段并新增 basis。
    basis_model = _load("app.aggregates.models.MarketBasis")
    assert _parse(basis_model, output["basis"]).model_dump(mode="json") == payload["basis"]  # 出处：T-A209 §3.2，同形。


@pytest.mark.xfail(strict=True, reason=REASON)
def test_daily_report_market_accepts_basis_and_data_status_block() -> None:
    """出处：T-A209 §3.2、API §5.3；检查完整日报中的嵌套市场 schema。"""
    _load("app.reports.models.Market", fields=("basis", "data_status", "data_as_of", "gaps"))
    model = _load("app.reports.models.DailyReport")
    market = dict(_daily_market(), basis=_basis(), data_status="unavailable", data_as_of=None, gaps=[])
    payload = {
        "date": SOURCE_TIME.date().isoformat(), "generated_at": FETCHED_TIME.isoformat(),
        "account_id": None, "market": market, "account": None,
        "reconciliation": {"status": "not_imported", "as_of": None, "diff_count": 0, "important_count": 0},
        "stocks": [], "pending": {"plan_drafts": 0, "active_reasons": 0},
        "explanation": {"source": "template", "text": "合成日报", "llm_call_id": None},
        "evidence": [], "data_status": "unavailable", "data_as_of": None, "gaps": [],
    }
    output = _parse(model, payload).model_dump(mode="json")
    assert output["market"] == market  # 出处：T-A209 §3.2，DailyReport.market 新增两个块。


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize("known", [False, True])
def test_project_old_overview_preserves_old_or_null_time(known: bool) -> None:
    """出处：T-A209 §3.2、API §7.3、§1.1 A-12；旧 GET 响应只读缺省投影。"""
    project = _load("app.aggregates.market_projection.project_market_overview")
    model = _load("app.aggregates.models.MarketOverview", fields=("basis",))
    payload = _overview(known=known)
    original = deepcopy(payload)
    projected = project(payload, now=NOW)
    assert isinstance(projected, model)  # 出处：T-B187 实现约定、T-A209 §3.2，返回模型。
    output = projected.model_dump(mode="json")
    for key, value in original.items():
        assert output[key] == value  # 出处：T-A209 §3.2、API §7.3，旧字段及旧时点保留。
    assert output["basis"] == _basis()  # 出处：T-A209 §3.2，旧响应不伪造批次/资格/来源。
    assert output["basis"]["observed_date"] != NOW.date().isoformat()  # 出处：T-A209 §3.2，不补当前观察日。
    assert output["data_as_of"] != NOW.isoformat()  # 出处：API §1.1 A-12，不用投影时刻。
    assert payload == original  # 出处：T-A209 §3.2，只读缺省投影。


@pytest.mark.xfail(strict=True, reason=REASON)
@pytest.mark.parametrize("breadth", [False, True])
def test_project_old_daily_market_without_status_or_flat(breadth: bool) -> None:
    """出处：T-A209 §2、§3.2、API §5.3、§1.1 A-12；不从生成时间补造市场事实。"""
    project = _load("app.aggregates.market_projection.project_daily_report_market")
    model = _load("app.reports.models.Market", fields=("basis", "data_status", "data_as_of", "gaps"))
    payload = _daily_market(breadth=breadth)
    original = deepcopy(payload)
    projected = project(payload, now=NOW)
    assert isinstance(projected, model)  # 出处：T-B187 实现约定、T-A209 §3.2，返回模型。
    output = projected.model_dump(mode="json")
    for key, value in original.items():
        assert output[key] == value  # 出处：T-A209 §3.2、API §5.3，旧 breadth 无 flat，按原形映射。
    assert output["basis"] == _basis()  # 出处：T-A209 §3.2，旧存档 basis 只做未知缺省。
    assert output["basis"]["observed_date"] != NOW.date().isoformat()  # 出处：T-A209 §3.2，不补当前日期。
    assert output["data_as_of"] is None  # 出处：API §1.1 A-12，无可信输入时点则 null。
    assert output["data_as_of"] != NOW.isoformat()  # 出处：T-A209 §3.2，禁止使用投影时刻。
    assert output["data_status"] in {"partial", "unavailable"}  # 出处：T-A209 §2，未知不标 fresh/pending。
    assert isinstance(output["gaps"], list) and output["gaps"]  # 出处：T-A209 §2，未知字段解释缺口。
    assert payload == original  # 出处：T-A209 §3.2，旧存档只读投影。
