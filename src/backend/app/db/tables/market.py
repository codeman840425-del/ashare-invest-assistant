"""共享行情 schema ``market``（plan §3.3「快照与共享行情」「实时」、§3A；T-O08 §13 对接）。

- 证券标识统一用文本 ``code``（如 ``600519.SH``），与 plan §3.3 和 ops policies.conf 的
  ``security_id/code`` 候选一致；plan §3A.6 的 ``security_id`` 不使用（不存在 uuid 证券实体）。
- hypertable（建表后由迁移 ``create_hypertable(..., create_default_indexes => false)`` 转换，
  chunk 间隔与 deploy/db/timescale/policies.conf 一致；压缩/保留/连续聚合由运维脚本负责）
  的主键与唯一约束都包含时间列（TimescaleDB 要求）。不从其他表建外键指向 hypertable。
- ``minute_bars.ts`` 是 **bar 结束时间**（契约 Bar.ts：09:31 表示 09:30–09:31 这一根）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
    text,
)

from app.db.base import (
    MARKET,
    day,
    jsonb,
    metadata,
    money,
    num,
    one_of,
    pk_uuid,
    text_array,
    ts,
    txt,
    uuid_col,
)
from app.schemas.enums import BarAdjust, Board, ListingStatus, SecurityRiskFlag, SecurityType


def _now(name: str) -> Column[Any]:
    return ts(name, nullable=False, default_now=True)


# 证券公开主数据，全站一份（v0.2.7 #19；不存公司全称）
securities = Table(
    "securities",
    metadata,
    txt("code", nullable=False, primary_key=True),
    txt("type", nullable=False),  # security_type；ETF 纳入但策略不运行（v0.2.7 Q3）
    txt("name", nullable=False),
    txt("exchange", nullable=False),
    txt("board"),
    day("list_date"),
    txt("listing_status"),
    _now("updated_at"),
    txt("list_date_basis"),
    day("delist_date"),
    txt("risk_flag"),
    txt("name_norm"),
    text_array("name_initials"),
    txt("master_source"),  # 来源待 plan 第 9 节问题 52 / T-A04
    ts("master_as_of"),
    one_of("exchange", ["SH", "SZ", "BJ"]),
    one_of("type", SecurityType),
    one_of("board", Board),
    one_of("listing_status", ListingStatus),
    one_of("list_date_basis", ["listing", "neeq_select"]),
    one_of("risk_flag", SecurityRiskFlag),
    schema=MARKET,
)
Index(
    "ix_securities_name_norm_trgm",
    securities.c.name_norm,
    postgresql_using="gin",
    postgresql_ops={"name_norm": "gin_trgm_ops"},
)
Index("ix_securities_name_initials", securities.c.name_initials, postgresql_using="gin")

security_name_history = Table(
    "security_name_history",
    metadata,
    txt("code", nullable=False, primary_key=True),
    txt("name", nullable=False, primary_key=True),
    txt("name_norm"),
    day("valid_from"),
    day("valid_until"),
    txt("master_source"),
    _now("recorded_at"),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    schema=MARKET,
    comment="曾用名（契约 SecurityProfile.former_names；T007 §5）",
)
Index(
    "ix_security_name_history_name_norm_trgm",
    security_name_history.c.name_norm,
    postgresql_using="gin",
    postgresql_ops={"name_norm": "gin_trgm_ops"},
)

security_code_history = Table(
    "security_code_history",
    metadata,
    txt("old_code", nullable=False, primary_key=True),
    txt("code", nullable=False),
    day("valid_until"),
    txt("master_source"),
    _now("recorded_at"),
    CheckConstraint("old_code <> code", name="differs"),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    schema=MARKET,
    comment="旧代码 → 新代码（北交所代码切换等；SecurityProfile.code_history、former_code）",
)
Index("ix_security_code_history_code", security_code_history.c.code)

security_risk_flag_history = Table(
    "security_risk_flag_history",
    metadata,
    txt("code", nullable=False, primary_key=True),
    txt("risk_flag"),
    day("valid_from", nullable=False, primary_key=True),
    day("valid_until"),
    txt("master_source"),
    _now("recorded_at"),
    one_of("risk_flag", SecurityRiskFlag),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    schema=MARKET,
    comment="风险警示变化历史（risk_flag 为 null 表示摘帽）",
)

trading_calendar = Table(
    "trading_calendar",
    metadata,
    Column("date", Date, primary_key=True),
    Column("is_open", Boolean, nullable=False),
    schema=MARKET,
)

daily_bars = Table(
    "daily_bars",
    metadata,
    txt("code", nullable=False),
    day("trade_date", nullable=False),
    txt("adj_type", nullable=False, server_default=text("'none'")),
    money("open"),
    money("high"),
    money("low"),
    money("close"),
    money("volume"),
    money("amount"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "trade_date", "adj_type"),
    one_of("adj_type", BarAdjust),
    schema=MARKET,
    comment="hypertable（trade_date，chunk 1 年）",
)

quotes_snapshot = Table(
    "quotes_snapshot",
    metadata,
    txt("code", nullable=False),
    ts("ts", nullable=False),
    money("price"),
    num("pct_change"),
    jsonb("payload"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "ts"),
    schema=MARKET,
    comment="只保留当日 + 近 5 日（清理由后端定时任务做）",
)

financial_reports = Table(
    "financial_reports",
    metadata,
    pk_uuid(),
    txt("code", nullable=False),
    txt("report_type", nullable=False),
    day("period_end", nullable=False),
    jsonb("payload", nullable=False),
    txt("payload_hash", nullable=False),
    day("announce_date"),
    ts("available_from"),
    _now("first_seen_at"),
    _now("last_seen_at"),
    one_of("report_type", ["balance", "income", "cashflow", "pershareindex"]),
    UniqueConstraint("code", "report_type", "period_end", "payload_hash"),
    schema=MARKET,
    comment="数据变化时新增行（保留重述历史，按 first_seen_at / available_from 做 as-of）",
)

fund_flows = Table(
    "fund_flows",
    metadata,
    txt("code", nullable=False),
    day("trade_date", nullable=False),
    jsonb("payload"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "trade_date"),
    schema=MARKET,
    comment="hypertable（trade_date，chunk 1 年）",
)

factor_values = Table(
    "factor_values",
    metadata,
    txt("code", nullable=False),
    day("trade_date", nullable=False),
    txt("factor_id", nullable=False),
    num("value"),
    txt("calc_version"),
    _now("fetched_at"),
    ts("available_from"),
    _now("first_seen_at"),
    PrimaryKeyConstraint("code", "trade_date", "factor_id"),
    schema=MARKET,
    comment="hypertable（trade_date，chunk 1 个月：plan §3.3；§3A.6 写 1 年，内部冲突见报告）",
)

announcements = Table(
    "announcements",
    metadata,
    pk_uuid(),
    txt("code", nullable=False),
    ts("published_at", nullable=False),
    txt("title", nullable=False),
    txt("summary"),
    txt("url"),
    txt("category"),
    txt("level"),
    txt("source", nullable=False, server_default=text("'mairui'")),
    _now("first_seen_at"),
    UniqueConstraint("code", "published_at", "title"),
    schema=MARKET,
)
Index("ix_announcements_code_published", announcements.c.code, announcements.c.published_at.desc())

qa_items = Table(
    "qa_items",
    metadata,
    pk_uuid(),
    txt("code", nullable=False),
    txt("question", nullable=False),
    txt("answer"),
    ts("asked_at"),
    ts("answered_at"),
    _now("first_seen_at"),
    schema=MARKET,
)

market_events = Table(
    "market_events",
    metadata,
    pk_uuid(),
    txt("code"),
    txt("type", nullable=False),
    day("event_date", nullable=False),
    jsonb("payload"),
    _now("first_seen_at"),
    uuid_col("event_definition_id", fk="app.event_definitions.id"),
    txt("source", nullable=False, server_default=text("'rule'")),
    num("confidence"),
    txt("original_title"),
    txt("original_url"),
    txt("review_status"),
    one_of("source", ["rule", "llm"]),
    schema=MARKET,
)

realtime_quotes = Table(
    "realtime_quotes",
    metadata,
    txt("code", nullable=False),
    ts("ts", nullable=False),
    money("price"),
    money("open"),
    money("high"),
    money("low"),
    money("pre_close"),
    money("volume"),
    money("amount"),
    num("pct_change"),
    txt("source"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "ts"),
    one_of("source", ["ssjy_more", "ssjy_all", "real_all"]),
    schema=MARKET,
    comment="hypertable（ts=行情时间，chunk 1 天）；按分钟降采样",
)

minute_bars = Table(
    "minute_bars",
    metadata,
    txt("code", nullable=False),
    ts("ts", nullable=False, comment="bar 结束时间（契约 Bar.ts）：09:31 表示 09:30–09:31"),
    money("open"),
    money("high"),
    money("low"),
    money("close"),
    money("volume"),
    money("amount"),
    txt("source"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "ts"),
    one_of("source", ["pro_latest", "pro_history"]),
    schema=MARKET,
    comment="hypertable（ts，chunk 1 天）；ts 为 bar 结束时间",
)

feature_bars_daily = Table(
    "feature_bars_daily",
    metadata,
    txt("code", nullable=False),
    day("trade_date", nullable=False),
    txt("feature_set_version", nullable=False),
    jsonb("values", nullable=False),
    _now("computed_at"),
    PrimaryKeyConstraint("code", "trade_date", "feature_set_version"),
    schema=MARKET,
    comment="hypertable（trade_date，chunk 1 年）；唯一特征管线产出",
)

raw_payloads = Table(
    "raw_payloads",
    metadata,
    pk_uuid(),
    txt("endpoint", nullable=False, comment="接口路径模板，不含 licence"),
    txt("params_hash", nullable=False),
    _now("fetched_at"),
    txt("status"),
    jsonb("body"),
    txt("body_hash"),
    Column("pinned", Boolean, nullable=False, server_default=text("false")),
    schema=MARKET,
    comment="保留 90 天（被快照引用的 pinned=true 永久保留）",
)
Index("ix_raw_payloads_endpoint_params", raw_payloads.c.endpoint, raw_payloads.c.params_hash)
