"""T006e / 契约 v0.2.6（T-A07）：HorizonCap.kind 改为 gate | data_missing

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02 07:00:00+08:00

契约 v0.2.6 §0 第 10 项（T006e 裁定 2，**不兼容变更**）、plan §3.3
``symbol_horizon_assessments.caps``：

- ``caps[].kind`` 取值由 ``data_missing | requires`` 改为 ``gate | data_missing``：
  HG1–HG6 命中 → ``gate``（``rule_id`` 为 ``HGn``，判 0 分的 HG1–HG3 记 ``cap: 0``，
  ``inputs_missing`` 为 ``[]``）；LG0/LG0B 的 ``else_cap`` → ``data_missing``；``IT0`` 的
  ``else_score: 0`` 是分数，不进 caps。
- 新 CHECK 额外要求 ``kind = gate`` 时 ``rule_id`` 匹配 ``^HG[1-6]$`` 且 ``inputs_missing`` 为空。
- ``symbol_horizon_assessments`` 只追加（触发器），旧行不能改写：库里已有 ``kind = requires``
  的行时**升级明确失败**（不静默改写，需人工处理）；downgrade 时已有 ``kind = gate`` 的行同样失败。
- 分类器版本仍为 1.2.0（``version_no: 3``）：plan §6.1 的规则未变，只加注释；分类器运行时尚未实现，
  输出按本约束生成即可。
- 0001–0005 不改。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "app"
T = "symbol_horizon_assessments"
NAME = "ck_symbol_horizon_assessments_caps_shape"

#: 与 app/db/tables/strategy.py 的 HORIZON_CAP_BAD_ITEM 生成结果逐字一致（v0.2.6）
_CAPS_CHECK_NEW = (
    "jsonb_typeof(caps) = 'array' AND NOT jsonb_path_exists(caps, '$[*] ? (@.type() != \"objec"
    't" || !(@.horizon.type() == "string") || !(@.horizon == "intraday_t" || @.horizon == "sh'
    'ort" || @.horizon == "swing" || @.horizon == "long") || !(@.cap.type() == "number") || @'
    '.cap < 0 || @.cap > 100 || @.cap != @.cap.floor() || !(@.kind.type() == "string") || !(@'
    '.kind == "gate" || @.kind == "data_missing") || !(@.rule_id.type() == "string" || @.rule'
    '_id.type() == "null") || !(@.inputs_missing.type() == "array") || (@.kind == "gate" && !'
    '(@.rule_id.type() == "string" && @.rule_id like_regex "^HG[1-6]$")) || (@.kind == "gate"'
    " && @.inputs_missing.size() != 0))')"
)

#: 0003 的原约束（downgrade 恢复用）
_CAPS_CHECK_OLD = (
    "jsonb_typeof(caps) = 'array' AND NOT jsonb_path_exists(caps, '$[*] ? (@.type() != \"objec"
    't" || !(@.horizon.type() == "string") || !(@.horizon == "intraday_t" || @.horizon == "sh'
    'ort" || @.horizon == "swing" || @.horizon == "long") || !(@.cap.type() == "number") || @'
    '.cap < 0 || @.cap > 100 || @.cap != @.cap.floor() || !(@.kind.type() == "string") || !(@'
    '.kind == "data_missing" || @.kind == "requires") || !(@.rule_id.type() == "string" || @.'
    'rule_id.type() == "null") || !(@.inputs_missing.type() == "array"))\')'
)


#: 常量 SQL（不拼接）：只追加表的旧行不能改写 → 有冲突取值时迁移明确失败
_FAIL_IF_REQUIRES_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.symbol_horizon_assessments
             WHERE jsonb_path_exists(caps, '$[*] ? (@.kind == "requires")')) THEN
    RAISE EXCEPTION '0006：symbol_horizon_assessments.caps 仍有 kind=requires 的元素，需人工处理'
      USING ERRCODE = 'check_violation';
  END IF;
END $$;
"""

_FAIL_IF_GATE_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.symbol_horizon_assessments
             WHERE jsonb_path_exists(caps, '$[*] ? (@.kind == "gate")')) THEN
    RAISE EXCEPTION '0006：symbol_horizon_assessments.caps 仍有 kind=gate 的元素，需人工处理'
      USING ERRCODE = 'check_violation';
  END IF;
END $$;
"""


def _set_check(sql: str) -> None:
    op.drop_constraint(op.f(NAME), T, type_="check", schema=S)
    op.create_check_constraint(op.f(NAME), T, sql, schema=S)


def upgrade() -> None:
    op.execute(_FAIL_IF_REQUIRES_SQL)
    _set_check(_CAPS_CHECK_NEW)


def downgrade() -> None:
    op.execute(_FAIL_IF_GATE_SQL)
    _set_check(_CAPS_CHECK_OLD)
