"""T-B03 认证与同意：consents.kind 增加 terms；max_single_position_pct 列注释

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01 22:00:00+00:00

- ``app.consents.kind``：契约 §7.1 ``POST /me/consents`` 的 ``key`` 有 ``terms``（用户协议），
  plan §3.3 的 kind 列表里没有 → CHECK 增加 ``terms``
  （与 0001 补 ``signal_risk_disclosure`` 同理）。
- ``app.user_profiles.max_single_position_pct``：评审 F8，范围不在库里写死（随 ``risk_controls``
  配置变化），只加列注释说明由 API 校验。
- downgrade：若已有 ``kind = 'terms'`` 的行，恢复旧 CHECK 会失败，需人工处理（只追加表不删历史行）。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"

_KINDS_OLD = (
    "privacy_policy",
    "sensitive_financial_info",
    "risk_disclosure",
    "email_notification",
    "signal_risk_disclosure",
)
_KINDS_NEW = (*_KINDS_OLD, "terms")
_F8_COMMENT = "范围由 API 校验，以 risk_controls 为准"


def _kind_check(kinds: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_consents_kind"), "consents", type_="check", schema=S)
    op.create_check_constraint(
        op.f("ck_consents_kind"), "consents", _kind_check(_KINDS_NEW), schema=S
    )
    op.execute(f"COMMENT ON COLUMN {S}.user_profiles.max_single_position_pct IS '{_F8_COMMENT}'")


def downgrade() -> None:
    op.execute(f"COMMENT ON COLUMN {S}.user_profiles.max_single_position_pct IS NULL")
    op.drop_constraint(op.f("ck_consents_kind"), "consents", type_="check", schema=S)
    op.create_check_constraint(
        op.f("ck_consents_kind"), "consents", _kind_check(_KINDS_OLD), schema=S
    )
