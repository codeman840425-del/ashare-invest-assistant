"""T-B03f：评审返修（review-be607b3 m1、review-8fd9502 m1）

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-02 09:40:00+08:00

- ``app.user_data_licence_cooldowns.fingerprint`` 列注释与实现对齐（0012 已在共享库
  aia-t01-postgres-1 应用到 0014，按规则不改 0012，用 ``COMMENT ON COLUMN``）：实际输入是
  user_id 与去重 HMAC（``app.licences.seal.cooldown_fingerprint``），不是明文证书。
- ``app.purge_pii_key``：删号匿名化审计 detail 时不再把“id 型键”（user_id(s)、target_user_id、
  actor_user_id、licence_id、account_id、profile_id 等）整键删除；这些键的值改由
  ``app.purge_scrub_json`` 的“值提到被删用户的 id 才删”规则处理：字符串值等于/包含被删用户
  （及其证书/画像/账户）id 时删键，数组只删匹配的元素，其他用户的 id 保留（例如管理员对
  他人操作的审计 ``user_ids: [bob, carol]`` 删除 bob 后保留 ``[carol]``）。
  触发器 ``purge_anonymize_ok`` 调用同一函数，期望值随之一致，无需改动。

downgrade：注释与函数恢复为 0013 的定义。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FP_COMMENT_NEW = "HMAC(K_cooldown, user_id||0x00||licence_hmac)"
FP_COMMENT_OLD = "HMAC(K_cooldown, user_id||licence)"

#: 0013 的 PII 键（按原顺序）；新定义去掉 ID_KEYS
PII_KEYS_0013 = (  # noqa: SIM905 —— 与 0013 的正则逐项对应，便于核对
    "security_code symbol name username user_name email phone address path filename file mask "
    "masked suffix last4 amount qty quantity quantities price cost fee cash cashes balance "
    "market_value user_agent ip apply_note note reason comment remark memo text description "
    "display_name user_id target_user_id actor_user_id licence_id license_id account_id "
    "profile_id shareholder_code broker_account"
).split()
ID_KEYS = frozenset(
    {
        "user_id",
        "target_user_id",
        "actor_user_id",
        "licence_id",
        "license_id",
        "account_id",
        "profile_id",
    }
)


def _pii_key_sql(keys: Sequence[str]) -> str:
    alt = "|".join(keys)
    return (
        "CREATE OR REPLACE FUNCTION app.purge_pii_key(k text) RETURNS boolean\n"
        "LANGUAGE sql IMMUTABLE AS $$\n"
        f"  SELECT lower(k) ~ '(^|_)({alt})(s|es)?$'\n"
        "$$;"
    )


def _comment(text: str) -> None:
    lit = text.replace("'", "''")
    op.execute(f"COMMENT ON COLUMN app.user_data_licence_cooldowns.fingerprint IS '{lit}'")


def upgrade() -> None:
    _comment(FP_COMMENT_NEW)
    op.execute(_pii_key_sql([k for k in PII_KEYS_0013 if k not in ID_KEYS]))


def downgrade() -> None:
    op.execute(_pii_key_sql(PII_KEYS_0013))
    _comment(FP_COMMENT_OLD)
