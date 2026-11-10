"""共享行情 schema ``market``（plan §3.3「快照与共享行情」「实时」、§3A；T-O08 §13 对接）。

- 证券标识统一用文本 ``code``（如 ``600519.SH``），与 plan §3.3 和 ops policies.conf 的
  ``security_id/code`` 候选一致；plan §3A.6 的 ``security_id`` 不使用（不存在 uuid 证券实体）。
- hypertable（建表后由迁移 ``create_hypertable(..., create_default_indexes => false)`` 转换，
  chunk 间隔与 deploy/db/timescale/policies.conf 一致；压缩/保留/连续聚合由运维脚本负责）
  的主键与唯一约束都包含时间列（TimescaleDB 要求）。不从其他表建外键指向 hypertable。
- ``minute_bars.ts`` 是 **bar 结束时间**（契约 Bar.ts：09:31 表示 09:30–09:31 这一根）。
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    UniqueConstraint,
    column,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ExcludeConstraint

from app.db.base import (
    MARKET,
    boolean,
    day,
    integer,
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
from app.schemas.enums import (
    BarAdjust,
    Board,
    ListingStatus,
    SecurityReconciliationKind,
    SecurityReconciliationSource,
    SecurityRiskFlag,
    SecurityType,
)


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
    day("missing_since"),  # T-B51：进入 missing_from_list 的快照日期
    day("last_seen_on"),  # T-B51：最近一次出现在交易所当前名单的快照日期
    jsonb("field_sources"),  # T-B51：字段 → exchange / cninfo
    one_of("exchange", ["SH", "SZ", "BJ"]),
    one_of("type", SecurityType),
    one_of("board", Board),
    one_of("listing_status", ListingStatus),
    one_of("list_date_basis", ["listing", "neeq_select"]),
    one_of("risk_flag", SecurityRiskFlag),
    schema=MARKET,
)
Index("ix_securities_exchange_listing_status", securities.c.exchange, securities.c.listing_status)
# T-B51（plan 4.6.2）：原 name_norm / name_initials 上的 gin 索引已删除，
# 检索改走 security_search_terms


def _period_exclusion(table: str) -> ExcludeConstraint:
    """同一代码的有效期（半开区间 ``[valid_from, valid_until)``，null 表示至今）不得重叠。"""
    return ExcludeConstraint(
        (column("code"), "="),
        (text("daterange(valid_from, valid_until, '[)')"), "&&"),
        using="gist",
        name=f"ex_{table}_period",
    )


def _period_order(table: str) -> CheckConstraint:
    return CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="period_order")


MASTER_SNAPSHOT_SOURCES: Final = (
    "mairui_list",
    "sse_list",
    "sse_delist",
    "szse_list",
    "szse_delist",
    "szse_rename",
    "bse_list",
    "bse_delist",
    "bse_code_map",
    "cninfo",
    "akshare",
)
MASTER_REJECT_REASONS: Final = ("empty", "drop_pct", "key_missing", "parse_error")
MASTER_RUN_TRIGGERS: Final = ("beat_1800", "beat_0730", "manual", "bootstrap")
SEARCH_TERM_KINDS: Final = (
    "name",
    "name_initials",
    "former_name",
    "former_initials",
    "former_code",
)
LISTING_STATUS_REASONS: Final = (
    "exchange_list",
    "exchange_delist_list",
    "missing_from_list",
    "mairui_list",
)
RECONCILIATION_FIELDS: Final = ("name", "list_date", "delist_date", "exchange", "board")

master_snapshots = Table(
    "master_snapshots",
    metadata,
    Column("id", BigInteger, Identity(always=False), primary_key=True),
    txt("source", nullable=False),
    txt("url", nullable=False),
    ts("fetched_at", nullable=False),
    day("trade_date", nullable=False),
    integer("row_count"),
    txt("sha256", nullable=False),
    txt("parse_status", nullable=False),
    txt("reject_reason"),
    txt("raw_path"),
    one_of("source", MASTER_SNAPSHOT_SOURCES),
    one_of("parse_status", ["ok", "rejected", "failed"]),
    one_of("reject_reason", MASTER_REJECT_REASONS),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
    CheckConstraint("parse_status <> 'ok' OR reject_reason IS NULL", name="ok_no_reason"),
    UniqueConstraint("source", "sha256"),
    schema=MARKET,
    comment="交易所 / 巨潮 / AKShare 公开列表快照（plan 4.6.2；不含证书值）",
)
Index(
    "ix_master_snapshots_source_fetched_at",
    master_snapshots.c.source,
    master_snapshots.c.fetched_at.desc(),
)

master_runs = Table(
    "master_runs",
    metadata,
    Column("id", BigInteger, Identity(always=False), primary_key=True),
    ts("started_at", nullable=False, default_now=True),
    ts("finished_at"),
    txt("trigger", nullable=False),
    txt("status"),  # 运行中为 null
    Column(
        "snapshot_ids", ARRAY(BigInteger), nullable=False, server_default=text("'{}'::bigint[]")
    ),
    jsonb("stats", nullable=False, server_default=text("'{}'::jsonb")),
    one_of("trigger", MASTER_RUN_TRIGGERS),
    one_of("status", ["ok", "partial", "failed"]),
    schema=MARKET,
    comment="主数据同步运行记录（plan 4.6.2 / 4.6.5）",
)
Index("ix_master_runs_started_at", master_runs.c.started_at.desc())

security_name_history = Table(
    "security_name_history",
    metadata,
    txt("code", nullable=False),
    txt("name", nullable=False),
    day("valid_from", nullable=False),
    day("valid_until"),
    txt("source", nullable=False),
    Column("snapshot_id", BigInteger),
    _now("recorded_at"),
    PrimaryKeyConstraint("code", "valid_from"),
    one_of("source", ["szse_ssgsgmxx", "exchange_diff"]),
    _period_order("security_name_history"),
    _period_exclusion("security_name_history"),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    ForeignKeyConstraint(["snapshot_id"], ["market.master_snapshots.id"]),
    schema=MARKET,
    comment="简称历史 / 曾用名（契约 SecurityProfile.former_names；plan 4.6.2）",
)
Index("ix_security_name_history_name", security_name_history.c.name)

security_code_history = Table(
    "security_code_history",
    metadata,
    txt("code", nullable=False),
    txt("old_code", nullable=False),
    day("valid_from", nullable=False),
    day("valid_until"),
    txt("source", nullable=False),
    _now("recorded_at"),
    PrimaryKeyConstraint("code", "valid_from"),
    UniqueConstraint("old_code"),
    CheckConstraint("old_code <> code", name="differs"),
    one_of("source", ["bse_code_map"]),
    _period_order("security_code_history"),
    _period_exclusion("security_code_history"),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    schema=MARKET,
    comment="旧代码 → 当前代码（北交所代码对照；SecurityProfile.code_history、former_code）",
)

security_risk_flag_history = Table(
    "security_risk_flag_history",
    metadata,
    txt("code", nullable=False),
    txt("risk_flag"),
    day("valid_from", nullable=False),
    day("valid_until"),
    Column("snapshot_id", BigInteger),
    _now("recorded_at"),
    PrimaryKeyConstraint("code", "valid_from"),
    one_of("risk_flag", SecurityRiskFlag),
    _period_order("security_risk_flag_history"),
    _period_exclusion("security_risk_flag_history"),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    ForeignKeyConstraint(["snapshot_id"], ["market.master_snapshots.id"]),
    schema=MARKET,
    comment="风险警示变化历史（risk_flag 为 null 表示摘帽）",
)

security_listing_status_history = Table(
    "security_listing_status_history",
    metadata,
    txt("code", nullable=False),
    txt("listing_status", nullable=False),
    day("valid_from", nullable=False),
    day("valid_until"),
    Column("snapshot_id", BigInteger),
    txt("reason", nullable=False),
    _now("recorded_at"),
    PrimaryKeyConstraint("code", "valid_from"),
    one_of("listing_status", ListingStatus),
    one_of("reason", LISTING_STATUS_REASONS),
    _period_order("security_listing_status_history"),
    _period_exclusion("security_listing_status_history"),
    ForeignKeyConstraint(["code"], ["market.securities.code"]),
    ForeignKeyConstraint(["snapshot_id"], ["market.master_snapshots.id"]),
    schema=MARKET,
    comment="上市状态历史（plan 4.6.1 / 4.6.2）",
)

security_search_terms = Table(
    "security_search_terms",
    metadata,
    Column("id", BigInteger, Identity(always=False), primary_key=True),
    txt("code", nullable=False),
    txt("term_kind", nullable=False),
    txt("term", nullable=False),
    txt("source_name", nullable=False),
    boolean("is_st_stripped", nullable=False, server_default=text("false")),
    Column("variant_rank", SmallInteger, nullable=False, server_default=text("0")),
    Column("generator_version", SmallInteger, nullable=False),
    one_of("term_kind", SEARCH_TERM_KINDS),
    CheckConstraint("variant_rank >= 0", name="variant_rank"),
    UniqueConstraint("code", "term_kind", "term", "source_name"),
    ForeignKeyConstraint(["code"], ["market.securities.code"], ondelete="CASCADE"),
    schema=MARKET,
    comment="搜索词条（plan 4.6.3；契约 §7.3 /securities/search）",
)
Index(
    "ix_security_search_terms_term_pattern",
    security_search_terms.c.term,
    postgresql_ops={"term": "text_pattern_ops"},
)
Index(
    "ix_security_search_terms_term_trgm",
    security_search_terms.c.term,
    postgresql_using="gin",
    postgresql_ops={"term": "gin_trgm_ops"},
    postgresql_where=text("term_kind IN ('name', 'former_name')"),
)
Index("ix_security_search_terms_code", security_search_terms.c.code)

security_reconciliation_diffs = Table(
    "security_reconciliation_diffs",
    metadata,
    Column("id", BigInteger, Identity(always=False), primary_key=True),
    txt("kind", nullable=False),
    txt("source", nullable=False),
    txt("security_code", nullable=False),  # vendor_unknown 的代码不在 securities，不设外键
    txt("source_name"),
    txt("field"),
    txt("master_value"),
    txt("source_value"),
    # 只有 mairui_* 有；不设外键（证书删除后差异行仍可读，licence_owner 给 null）
    uuid_col("source_licence_id"),
    day("first_seen_on", nullable=False),
    day("last_seen_on", nullable=False),
    integer("seen_days", nullable=False, server_default=text("1")),
    txt("status", nullable=False, server_default=text("'open'")),
    day("resolved_on"),
    one_of("kind", SecurityReconciliationKind),
    one_of("source", SecurityReconciliationSource),
    one_of("field", RECONCILIATION_FIELDS),
    one_of("status", ["open", "resolved"]),
    CheckConstraint(
        "(source IN ('mairui_lists', 'mairui_real_all')) = (source_licence_id IS NOT NULL)",
        name="licence_only_mairui",
    ),
    CheckConstraint("(kind = 'field_mismatch') = (field IS NOT NULL)", name="field_only_mismatch"),
    CheckConstraint("(status = 'resolved') = (resolved_on IS NOT NULL)", name="resolved_on"),
    CheckConstraint("last_seen_on >= first_seen_on AND seen_days >= 1", name="seen"),
    schema=MARKET,
    comment="证券主数据对账差异（plan 4.6.4；契约 §7.9）；kind=vendor_unknown 且 open = 隔离区",
)
Index(
    "uq_security_reconciliation_diffs_open",
    security_reconciliation_diffs.c.kind,
    security_reconciliation_diffs.c.source,
    security_reconciliation_diffs.c.security_code,
    security_reconciliation_diffs.c.field,
    security_reconciliation_diffs.c.source_licence_id,
    unique=True,
    postgresql_nulls_not_distinct=True,
    postgresql_where=text("status = 'open'"),
)
Index(
    "ix_security_reconciliation_diffs_status_last_seen",
    security_reconciliation_diffs.c.status,
    security_reconciliation_diffs.c.last_seen_on.desc(),
    security_reconciliation_diffs.c.id.desc(),
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
    money("pre_close"),
    boolean("is_suspended"),
    txt("source"),
    uuid_col("source_licence_id"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "trade_date", "adj_type"),
    one_of("adj_type", BarAdjust),
    CheckConstraint(
        "source IS NULL OR source IN ('fake', 'mairui', 'tdx_local')",
        name="source_allowed",
    ),
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

# intraday-bars §1.3：新写入只用 mairui、tdx_local；pro_* 只为兼容基线保留（0034）。
MINUTE_BAR_SOURCES = ("pro_latest", "pro_history", "mairui", "tdx_local")

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
    uuid_col("source_licence_id"),
    PrimaryKeyConstraint("code", "ts"),
    one_of("source", MINUTE_BAR_SOURCES),
    schema=MARKET,
    comment="hypertable（ts，chunk 1 天）；ts 为 bar 结束时间",
)

# T-B133 / 0034：只存通达信 .lc5 历史；以后的 5 分钟线读取时由 1 分钟聚合（intraday-bars §2.2）。
minute5_bars = Table(
    "minute5_bars",
    metadata,
    txt("code", nullable=False),
    ts("ts", nullable=False, comment="bar 结束时间：09:35 表示 09:30–09:35"),
    money("open"),
    money("high"),
    money("low"),
    money("close"),
    money("volume"),
    money("amount"),
    txt("source"),
    uuid_col("source_licence_id"),
    _now("fetched_at"),
    PrimaryKeyConstraint("code", "ts"),
    one_of("source", MINUTE_BAR_SOURCES),
    schema=MARKET,
    comment="hypertable（ts，chunk 7 天）；ts 为 bar 结束时间；只存通达信 .lc5 历史",
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
