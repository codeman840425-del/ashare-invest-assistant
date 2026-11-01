"""T-B02y：契约 v0.2.7 同步（T-A08 fa6d55d；Q3 编排者裁定 35517f8）

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02 07:00:00+08:00

1. ``app.strategy_instances``（契约 §5.1 ``StrategyInstance``、§6.0A；plan §3.3）：
   加 ``horizon``、``paused_by``、``pause_reason_code``、``paused_until``、``updated_at``、
   ``archived_at``；``origin`` 加 ``system``；暂停字段与归档字段的一致性 CHECK；
   索引 ``(user_id, status, created_at desc, id desc)``。``horizon`` 可空（旧行没有值；
   T-B32 写入时必填）。升级时先回填（评审 M1）：已有 ``paused`` 行 ``paused_by='user'``；
   已有 ``archived`` 行 ``archived_at`` = 最近一次 archived 事件时间，否则 ``confirmed_at``，
   否则 ``created_at``。
2. ``market.securities``（plan §3.3 v0.2.7，证券公开主数据，全站一份）：加 ``type``
   （stock/cdr/etf/index，v0.2.8 顺序；**ETF 按 Q3 裁定纳入**）、``list_date_basis``、
   ``delist_date``、
   ``risk_flag``、``name_norm``、``name_initials``、``master_source``、``master_as_of``；
   ``status`` 改名为 ``listing_status`` 并加 CHECK；删除 ``industry_codes``（行业移到按证书的
   表，由 T-B06 建）。主键仍是文本 ``code``（与全部 app 表的 ``security_code`` 一致，不引入
   uuid ``security_id``）。若表中已有行，``type`` 无法推断 → 迁移报错停止，不猜测。
   另建 ``security_name_history``、``security_code_history``、``security_risk_flag_history``；
   ``pg_trgm`` 扩展与 ``gin (name_norm gin_trgm_ops)``、``gin (name_initials)`` 索引。
3. **策略不对 ETF 运行**（plan 第 9 节 53）：``app.strategy_instances``（``security_code``
   非空时）与 ``app.candidate_signals`` 写入前检查 ``market.securities.type``，只允许
   ``stock``/``cdr``；查不到主数据也拒绝（失败即关闭）。应用层同口径：
   :mod:`app.strategy.eligibility`。

downgrade 会丢信息（评审 m4，有意接受）：``origin='system'`` 改回 ``user``；暂停原因/到期时间、
``archived_at``、``horizon``、证券 ``type`` 等新列与三张历史表随之删除；再升级时按上面的回填规则
重建 ``paused_by``/``archived_at``。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

A = "app"
M = "market"

HORIZONS = ("intraday_t", "short", "swing", "long")
REASON_CODES = (
    "DATA_STALE", "KEY_DATA_MISSING", "LOW_CONFIDENCE", "NON_TRADING_TIME", "SUSPENDED",
    "LIMIT_LOCKED", "ST_OR_DELISTING", "NEW_LISTING", "INSUFFICIENT_CASH", "T1_NOT_SELLABLE",
    "NO_POSITION", "POSITION_CAP_REACHED", "STRATEGY_BUDGET_EXHAUSTED",
    "SECTOR_EXPOSURE_EXCEEDED", "REGIME_MISMATCH", "SAME_DIRECTION_PLAN_EXISTS",
    "CONFLICTS_CONFIRMED_PLAN", "BLOCKLISTED", "COOLING_OFF", "LOSS_STREAK_PAUSE",
    "STRATEGY_CONFLICT", "USER_MUTED",
)  # fmt: skip
SECURITY_TYPES = ("stock", "cdr", "etf", "index")  # 契约 v0.2.8 §3 顺序
ELIGIBLE_TYPES = ("stock", "cdr")


def _in(col: str, vals: Sequence[str]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in vals) + ")"


GUARD_SQL = """
CREATE OR REPLACE FUNCTION app.reject_non_strategy_security() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  t text;
BEGIN
  IF NEW.security_code IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT s.type INTO t FROM market.securities s WHERE s.code = NEW.security_code;
  IF t IS NULL OR NOT (@ELIGIBLE@) THEN
    RAISE EXCEPTION '%.%：证券 % 的类型为 %，策略只对 stock/cdr 运行（ETF、指数不运行策略）',
      TG_TABLE_SCHEMA, TG_TABLE_NAME, NEW.security_code, coalesce(t, '未知')
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
""".replace("@ELIGIBLE@", _in("t", ELIGIBLE_TYPES))


def upgrade() -> None:
    tstz = sa.DateTime(timezone=True)

    # ---- 1. strategy_instances ----
    op.add_column("strategy_instances", sa.Column("horizon", sa.Text()), schema=A)
    op.add_column("strategy_instances", sa.Column("paused_by", sa.Text()), schema=A)
    op.add_column("strategy_instances", sa.Column("pause_reason_code", sa.Text()), schema=A)
    op.add_column("strategy_instances", sa.Column("paused_until", tstz), schema=A)
    op.add_column(
        "strategy_instances",
        sa.Column("updated_at", tstz, server_default=sa.func.now(), nullable=False),
        schema=A,
    )
    op.add_column("strategy_instances", sa.Column("archived_at", tstz), schema=A)
    op.drop_constraint(
        op.f("ck_strategy_instances_origin"), "strategy_instances", type_="check", schema=A
    )
    op.create_check_constraint(
        op.f("ck_strategy_instances_origin"),
        "strategy_instances",
        _in("origin", ("classifier", "user", "system")),
        schema=A,
    )
    op.create_check_constraint(
        op.f("ck_strategy_instances_horizon"),
        "strategy_instances",
        _in("horizon", HORIZONS),
        schema=A,
    )
    op.create_check_constraint(
        op.f("ck_strategy_instances_paused_by"),
        "strategy_instances",
        _in("paused_by", ("user", "system")),
        schema=A,
    )
    op.create_check_constraint(
        op.f("ck_strategy_instances_pause_reason_code"),
        "strategy_instances",
        _in("pause_reason_code", REASON_CODES),
        schema=A,
    )
    # 评审 review-T-B02y M1：先回填 0008 已有的暂停/归档行，再加一致性 CHECK。
    # 0008 只有用户暂停（无系统暂停）→ paused_by='user'，reason/until 保持 NULL。
    # archived_at 取最可信的来源：该实例最近一次 kind='archived' 的事件时间
    # （strategy_instance_events 只追加）；没有事件时退回 confirmed_at，再退回 created_at。
    # 不用 updated_at：它是本迁移新加的列，旧行的值是迁移执行时刻 now()。
    op.execute(
        "UPDATE app.strategy_instances SET paused_by = 'user' "
        "WHERE status = 'paused' AND paused_by IS NULL"
    )
    op.execute(
        """
        UPDATE app.strategy_instances i
           SET archived_at = coalesce(
                 (SELECT max(e.at) FROM app.strategy_instance_events e
                   WHERE e.instance_id = i.id AND e.kind = 'archived'),
                 i.confirmed_at, i.created_at)
         WHERE i.status = 'archived' AND i.archived_at IS NULL
        """
    )
    # 契约 §5.1：status != paused 时暂停字段全为 null；暂停时必须有 paused_by；
    # 用户暂停时 reason/until 为 null
    op.create_check_constraint(
        op.f("ck_strategy_instances_pause_fields"),
        "strategy_instances",
        "(status = 'paused' AND paused_by IS NOT NULL"
        " AND (paused_by = 'system' OR (pause_reason_code IS NULL AND paused_until IS NULL)))"
        " OR (status <> 'paused' AND paused_by IS NULL AND pause_reason_code IS NULL"
        " AND paused_until IS NULL)",
        schema=A,
    )
    op.create_check_constraint(
        op.f("ck_strategy_instances_archived_at"),
        "strategy_instances",
        "(status = 'archived') = (archived_at IS NOT NULL)",
        schema=A,
    )
    op.create_index(
        "ix_strategy_instances_user_status_created",
        "strategy_instances",
        ["user_id", "status", sa.text("created_at DESC"), sa.text("id DESC")],
        schema=A,
    )

    # ---- 2. market.securities ----
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM market.securities) THEN
            RAISE EXCEPTION '0009：market.securities 已有数据，无法推断 type'
              '（ETF 不能被当成股票），'
              '请先清空后由 T-B06 按交易所公开列表重新导入';
          END IF;
        END $$;
        """
    )
    op.add_column("securities", sa.Column("type", sa.Text(), nullable=False), schema=M)
    op.alter_column("securities", "status", new_column_name="listing_status", schema=M)
    op.add_column("securities", sa.Column("list_date_basis", sa.Text()), schema=M)
    op.add_column("securities", sa.Column("delist_date", sa.Date()), schema=M)
    op.add_column("securities", sa.Column("risk_flag", sa.Text()), schema=M)
    op.add_column("securities", sa.Column("name_norm", sa.Text()), schema=M)
    op.add_column("securities", sa.Column("name_initials", postgresql.ARRAY(sa.Text())), schema=M)
    op.add_column("securities", sa.Column("master_source", sa.Text()), schema=M)
    op.add_column("securities", sa.Column("master_as_of", tstz), schema=M)
    op.drop_column("securities", "industry_codes", schema=M)
    op.create_check_constraint(
        op.f("ck_securities_type"), "securities", _in("type", SECURITY_TYPES), schema=M
    )
    op.create_check_constraint(
        op.f("ck_securities_board"),
        "securities",
        _in("board", ("main", "chinext", "star", "bse")),
        schema=M,
    )
    op.create_check_constraint(
        op.f("ck_securities_listing_status"),
        "securities",
        _in("listing_status", ("listed", "delisting_period", "delisted", "missing_from_list")),
        schema=M,
    )
    op.create_check_constraint(
        op.f("ck_securities_list_date_basis"),
        "securities",
        _in("list_date_basis", ("listing", "neeq_select")),
        schema=M,
    )
    op.create_check_constraint(
        op.f("ck_securities_risk_flag"),
        "securities",
        _in("risk_flag", ("st", "star_st", "delisting")),
        schema=M,
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_securities_name_norm_trgm",
        "securities",
        ["name_norm"],
        schema=M,
        postgresql_using="gin",
        postgresql_ops={"name_norm": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_securities_name_initials",
        "securities",
        ["name_initials"],
        schema=M,
        postgresql_using="gin",
    )

    op.create_table(
        "security_name_history",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text()),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.Column("master_source", sa.Text()),
        sa.Column("recorded_at", tstz, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["code"], ["market.securities.code"],
            name=op.f("fk_security_name_history_code_securities"),
        ),
        sa.PrimaryKeyConstraint("code", "name", name=op.f("pk_security_name_history")),
        schema=M,
        comment="曾用名（契约 SecurityProfile.former_names；T007 §5）",
    )  # fmt: skip
    op.create_index(
        "ix_security_name_history_name_norm_trgm",
        "security_name_history",
        ["name_norm"],
        schema=M,
        postgresql_using="gin",
        postgresql_ops={"name_norm": "gin_trgm_ops"},
    )
    op.create_table(
        "security_code_history",
        sa.Column("old_code", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.Date()),
        sa.Column("master_source", sa.Text()),
        sa.Column("recorded_at", tstz, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["code"], ["market.securities.code"],
            name=op.f("fk_security_code_history_code_securities"),
        ),
        sa.PrimaryKeyConstraint("old_code", name=op.f("pk_security_code_history")),
        sa.CheckConstraint("old_code <> code", name=op.f("ck_security_code_history_differs")),
        schema=M,
        comment="旧代码 → 新代码（北交所代码切换等；SecurityProfile.code_history、former_code）",
    )  # fmt: skip
    op.create_index("ix_security_code_history_code", "security_code_history", ["code"], schema=M)
    op.create_table(
        "security_risk_flag_history",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("risk_flag", sa.Text()),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date()),
        sa.Column("master_source", sa.Text()),
        sa.Column("recorded_at", tstz, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["code"], ["market.securities.code"],
            name=op.f("fk_security_risk_flag_history_code_securities"),
        ),
        sa.PrimaryKeyConstraint(
            "code", "valid_from", name=op.f("pk_security_risk_flag_history")
        ),
        sa.CheckConstraint(
            "risk_flag IN ('st', 'star_st', 'delisting')",
            name=op.f("ck_security_risk_flag_history_risk_flag"),
        ),
        schema=M,
        comment="风险警示变化历史（risk_flag 为 null 表示摘帽）",
    )  # fmt: skip

    # ---- 3. 策略不对 ETF 运行 ----
    op.execute(GUARD_SQL)
    op.execute(
        "CREATE TRIGGER trg_strategy_instances_eligible_security"
        " BEFORE INSERT OR UPDATE OF security_code ON app.strategy_instances"
        " FOR EACH ROW EXECUTE FUNCTION app.reject_non_strategy_security()"
    )
    op.execute(
        "CREATE TRIGGER trg_candidate_signals_eligible_security"
        " BEFORE INSERT ON app.candidate_signals"
        " FOR EACH ROW EXECUTE FUNCTION app.reject_non_strategy_security()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_candidate_signals_eligible_security ON app.candidate_signals"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_strategy_instances_eligible_security ON app.strategy_instances"
    )
    op.execute("DROP FUNCTION IF EXISTS app.reject_non_strategy_security()")
    op.drop_table("security_risk_flag_history", schema=M)
    op.drop_table("security_code_history", schema=M)
    op.drop_table("security_name_history", schema=M)
    op.drop_index("ix_securities_name_initials", "securities", schema=M)
    op.drop_index("ix_securities_name_norm_trgm", "securities", schema=M)
    for ck in ("risk_flag", "list_date_basis", "listing_status", "board", "type"):
        op.drop_constraint(op.f(f"ck_securities_{ck}"), "securities", type_="check", schema=M)
    op.add_column("securities", sa.Column("industry_codes", postgresql.ARRAY(sa.Text())), schema=M)
    for col in (
        "master_as_of", "master_source", "name_initials", "name_norm", "risk_flag",
        "delist_date", "list_date_basis", "type",
    ):  # fmt: skip
        op.drop_column("securities", col, schema=M)
    op.alter_column("securities", "listing_status", new_column_name="status", schema=M)

    op.drop_index("ix_strategy_instances_user_status_created", "strategy_instances", schema=A)
    for ck in ("archived_at", "pause_fields", "pause_reason_code", "paused_by", "horizon"):
        op.drop_constraint(
            op.f(f"ck_strategy_instances_{ck}"), "strategy_instances", type_="check", schema=A
        )
    op.drop_constraint(
        op.f("ck_strategy_instances_origin"), "strategy_instances", type_="check", schema=A
    )
    op.execute(
        "UPDATE app.strategy_instances SET origin = 'user' WHERE origin = 'system'"
    )  # 降级只能把系统挂载并入 user（v0.2.6 没有 system）
    op.create_check_constraint(
        op.f("ck_strategy_instances_origin"),
        "strategy_instances",
        _in("origin", ("classifier", "user")),
        schema=A,
    )
    for col in (
        "archived_at", "updated_at", "paused_until", "pause_reason_code", "paused_by", "horizon",
    ):  # fmt: skip
        op.drop_column("strategy_instances", col, schema=A)
