"""T-B16 / 契约 v0.2.5（T-A06 减法）：删 consents、fit_ack 与一个原因码，加 hints

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02 06:30:00+08:00

用户 2026-11-02 决定不做同意流程与风险测评（plan §3.3、契约 v0.2.5 §0 A 表）：

- 删表 ``app.consents``（连同其不可变 / TRUNCATE 触发器）。表中已有的同意记录随表删除，
  这是 T-A06 的明确要求（“已建的 consents 由新迁移删除”）。
  ``legal_documents``、``legal_document_events``、``questionnaires``、``risk_assessments`` 与
  ``user_profiles.assessment_id`` / ``questionnaire_version`` 从未建过（0001–0004 都没有），
  无需处理。
- 删列 ``app.strategy_instances.fit_ack``（契约 v0.2.5：POST /strategy-instances 不再有 fit_ack）。
- ``app.non_executable_reasons.code`` 的 CHECK 去掉 ``PROFILE_OR_CONSENT_MISSING``（23 → 22）。
  若库里已有该原因码的行，**升级明确失败**（不静默删除，需人工处理）。
- ``app.symbol_horizon_assessments.hints jsonb NOT NULL DEFAULT '[]'``：HorizonHint[]
  （``{horizon, rule_id, text}``，分类器 1.2.0 ``mode: hint`` 规则的提示）+ 形状 CHECK。
- 分类器 v3（1.2.0）行：``horizon_classifier_versions`` 由分类器加载器从
  ``config/horizon_classifier.yaml`` 写入，迁移不插入（0001–0004 也未插 v1/v2）。
- 0001–0004 不改。

downgrade：重建空的 ``consents``（0004 的 CHECK，含 ``terms``）与触发器、加回可空 ``fit_ack``、
恢复 23 个原因码的 CHECK、删除 ``hints``。被删的同意记录与 fit_ack 值不能恢复。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"

_REASON_CODES_NEW = (
    "DATA_STALE",
    "KEY_DATA_MISSING",
    "LOW_CONFIDENCE",
    "NON_TRADING_TIME",
    "SUSPENDED",
    "LIMIT_LOCKED",
    "ST_OR_DELISTING",
    "NEW_LISTING",
    "INSUFFICIENT_CASH",
    "T1_NOT_SELLABLE",
    "NO_POSITION",
    "POSITION_CAP_REACHED",
    "STRATEGY_BUDGET_EXHAUSTED",
    "SECTOR_EXPOSURE_EXCEEDED",
    "REGIME_MISMATCH",
    "SAME_DIRECTION_PLAN_EXISTS",
    "CONFLICTS_CONFIRMED_PLAN",
    "BLOCKLISTED",
    "COOLING_OFF",
    "LOSS_STREAK_PAUSE",
    "STRATEGY_CONFLICT",
    "USER_MUTED",
)
_REMOVED_CODE = "PROFILE_OR_CONSENT_MISSING"
_REASON_CODES_OLD = (*_REASON_CODES_NEW, _REMOVED_CODE)

#: 0004 的 consents.kind（downgrade 重建用）
_CONSENT_KINDS = (
    "privacy_policy",
    "sensitive_financial_info",
    "risk_disclosure",
    "email_notification",
    "signal_risk_disclosure",
    "terms",
)

_HINTS_CHECK = (
    "jsonb_typeof(hints) = 'array' AND NOT jsonb_path_exists(hints, '$[*] ? ("
    '@.type() != "object" || !(@.horizon.type() == "string") || !(@.horizon == "intraday_t"'
    ' || @.horizon == "short" || @.horizon == "swing" || @.horizon == "long")'
    ' || !(@.rule_id.type() == "string") || @.rule_id == ""'
    ' || !(@.text.type() == "string") || @.text == "")\')'
)

#: 常量 SQL（不拼接）：库里仍有被删原因码的行 → 升级失败，不静默删除
_FAIL_IF_REMOVED_CODE_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.non_executable_reasons
             WHERE code = 'PROFILE_OR_CONSENT_MISSING') THEN
    RAISE EXCEPTION '0005：non_executable_reasons 仍有 PROFILE_OR_CONSENT_MISSING 行，需人工处理'
      USING ERRCODE = 'check_violation';
  END IF;
END $$;
"""


def _in(col: str, values: Sequence[str]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _set_reason_check(codes: Sequence[str]) -> None:
    op.drop_constraint(
        op.f("ck_non_executable_reasons_code"), "non_executable_reasons", type_="check", schema=S
    )
    op.create_check_constraint(
        op.f("ck_non_executable_reasons_code"),
        "non_executable_reasons",
        _in("code", codes),
        schema=S,
    )


def upgrade() -> None:
    op.execute(_FAIL_IF_REMOVED_CODE_SQL)
    _set_reason_check(_REASON_CODES_NEW)
    op.drop_table("consents", schema=S)
    op.drop_column("strategy_instances", "fit_ack", schema=S)
    op.add_column(
        "symbol_horizon_assessments",
        sa.Column(
            "hints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_symbol_horizon_assessments_hints_shape"),
        "symbol_horizon_assessments",
        _HINTS_CHECK,
        schema=S,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_symbol_horizon_assessments_hints_shape"),
        "symbol_horizon_assessments",
        type_="check",
        schema=S,
    )
    op.drop_column("symbol_horizon_assessments", "hints", schema=S)
    op.add_column(
        "strategy_instances",
        sa.Column("fit_ack", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=S,
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("doc_version", sa.Text(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.CheckConstraint(_in("kind", _CONSENT_KINDS), name=op.f("ck_consents_kind")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], name=op.f("fk_consents_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
        schema=S,
    )
    op.execute(
        f"CREATE TRIGGER trg_consents_immutable BEFORE UPDATE OR DELETE ON {S}.consents "
        "FOR EACH ROW EXECUTE FUNCTION app.reject_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER trg_no_truncate BEFORE TRUNCATE ON {S}.consents "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_truncate()"
    )
    _set_reason_check(_REASON_CODES_OLD)
