"""T-B16-core-r2：评审 45589c2 修复（plan §7.3 / §3.3，8a760d1 裁定）

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-02 07:45:00+08:00

- B1 ``app.users`` BEFORE INSERT/UPDATE 触发器 ``trg_users_purging_guard``：
  INSERT ``status='purging'`` 一律拒绝；只有 ``current_user = 'aia_maint'`` 能把 status UPDATE 成
  purging；行一旦 purging，任何 UPDATE 都拒绝（只能 DELETE）。这不是通用旁路：aia_maint 在其他
  不可变表上的权限与普通角色相同，仍只靠 ``purge_permits``（属主为 purging 用户）放行。
- B1 可延迟约束触发器 ``trg_users_purging_not_committed`` 改为按行：本事务置为 purging 的那一行，
  提交时必须已不存在（不再是“全库有无 purging 行”的全局检查）。
- B2 ``app.data_snapshots`` 新增 ``user_id``（FK users，可空）与 ``licence_id``（FK
  user_data_licences，可空）：含持仓/成交/账户派生内容的快照必须填 user_id（写入方实现时遵守）；
  ``purge_row_owner`` 认它们为属主，删除用户时物理删除。user_id 为空的快照只能存市场级内容。
- M1 ``account_reviews`` 的匿名化 UPDATE 还必须把 ``reason`` 置 NULL（任何被匿名化的行）。
- M2 ``audit_logs.detail`` 清理：新增 ``app.purge_scrub_json(jsonb, text[])``——去掉 PII 键（含复数
  形式）、自由文本键（reason/note/comment/remark/memo/text/description，含管理员填写的）、指向用户
  的键（user_id/target_user_id/username/licence_id/account_id …），以及值或键名包含该用户 id、其证书
  行/画像/账户 id 的项（``app.purge_ref_ids``）；只在 detail 里提到该用户的审计行也会被匿名化。
  保留 action、时间、管理员自己的 actor、非 PII 枚举（status、reason_code 等）。

downgrade：恢复 0011 的函数体与全局检查、删 data_snapshots 新列（已删除/已清空的数据不能恢复）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 允许把 users.status 写成 purging 的唯一数据库角色（ops 建角色与授权，见 reports/T-B16-core.md）
MAINT_ROLE = "aia_maint"

DIRECT_OWNER_TABLES = (
    "app.trades",
    "app.suggestions",
    "app.candidate_signals",
    "app.plan_drafts",
    "app.plan_draft_confirmations",
    "app.daily_reports",
    "app.user_profiles",
    "app.claims",
    "app.signal_events",
    "app.risk_events",
    "app.suggestion_user_actions",
    "app.symbol_horizon_assessments",
)

OWNER_FUNCTION = r"""
CREATE OR REPLACE FUNCTION app.purge_row_owner(tbl text, o jsonb) RETURNS uuid
LANGUAGE plpgsql STABLE AS $$
DECLARE
  base text := regexp_replace(tbl, '_(p[0-9]{6}|default)$', '');
  r uuid;
BEGIN
  CASE base
  WHEN __DIRECT__ THEN
    RETURN (o->>'user_id')::uuid;
  WHEN 'app.broker_position_snapshots' THEN
    SELECT a.user_id INTO r FROM app.accounts a WHERE a.id = (o->>'account_id')::uuid;
  WHEN 'app.broker_position_snapshot_items' THEN
    SELECT a.user_id INTO r FROM app.broker_position_snapshots s
      JOIN app.accounts a ON a.id = s.account_id WHERE s.id = (o->>'snapshot_id')::uuid;
  WHEN 'app.daily_report_items' THEN
    SELECT d.user_id INTO r FROM app.daily_reports d WHERE d.id = (o->>'report_id')::uuid;
  WHEN 'app.plan_versions' THEN
    SELECT p.user_id INTO r FROM app.action_plans p WHERE p.id = (o->>'plan_id')::uuid;
  WHEN 'app.plan_conditions' THEN
    SELECT p.user_id INTO r FROM app.plan_versions v
      JOIN app.action_plans p ON p.id = v.plan_id WHERE v.id = (o->>'plan_version_id')::uuid;
  WHEN 'app.review_versions' THEN
    SELECT v.user_id INTO r FROM app.reviews v WHERE v.id = (o->>'review_id')::uuid;
  WHEN 'app.reason_status_events' THEN
    SELECT n.user_id INTO r FROM app.non_executable_reasons n WHERE n.id = (o->>'reason_id')::uuid;
  WHEN 'app.candidate_versions' THEN
    SELECT c.user_id INTO r FROM app.research_candidates c WHERE c.id = (o->>'candidate_id')::uuid;
  WHEN 'app.strategy_instance_events' THEN
    SELECT i.user_id INTO r FROM app.strategy_instances i WHERE i.id = (o->>'instance_id')::uuid;
  WHEN 'app.risk_control_settings_history' THEN
    SELECT coalesce((o->>'user_id')::uuid, s.user_id) INTO r FROM app.risk_control_settings s
      WHERE s.id = (o->>'setting_id')::uuid;
  WHEN 'app.candidate_signal_events' THEN
    SELECT s.user_id INTO r FROM app.candidate_signals s WHERE s.id = (o->>'signal_id')::uuid;
  WHEN 'app.data_snapshots' THEN
    -- 0013（plan §3.3/§7.3 8a760d1）：带 user_id/licence_id 的快照属于该用户，删除时物理删除
    r := (o->>'user_id')::uuid;
    IF r IS NULL AND o->>'licence_id' IS NOT NULL THEN
      SELECT l.user_id INTO r FROM app.user_data_licences l WHERE l.id = (o->>'licence_id')::uuid;
    END IF;
  ELSE
    RETURN NULL;
  END CASE;
  RETURN r;
END $$;
""".replace("__DIRECT__", ", ".join(f"'{t}'" for t in DIRECT_OWNER_TABLES))

NEW_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION app.purge_pii_key(k text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT lower(k) ~ ('(^|_)(security_code|symbol|name|username|user_name|email|phone|address'
    || '|path|filename|file|mask|masked|suffix|last4|amount|qty|quantity|quantities|price|cost|fee'
    || '|cash|cashes|balance|market_value|user_agent|ip|apply_note|note|reason|comment|remark|memo'
    || '|text|description|display_name|user_id|target_user_id|actor_user_id|licence_id|license_id'
    || '|account_id|profile_id|shareholder_code|broker_account)(s|es)?$')
$$;

CREATE OR REPLACE FUNCTION app.purge_ref_ids(uids uuid[]) RETURNS text[]
LANGUAGE sql STABLE AS $$
  SELECT coalesce(array_agg(DISTINCT x), '{}') FROM (
    SELECT unnest(uids)::text AS x
    UNION SELECT id::text FROM app.user_data_licences WHERE user_id = ANY (uids)
    UNION SELECT id::text FROM app.user_profiles WHERE user_id = ANY (uids)
    UNION SELECT id::text FROM app.accounts WHERE user_id = ANY (uids)
  ) s
$$;

-- j 的任一字符串值或键名包含 ids 之一（子串）
CREATE OR REPLACE FUNCTION app.purge_json_mentions(j jsonb, ids text[]) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF j IS NULL OR ids IS NULL OR cardinality(ids) = 0 THEN RETURN false; END IF;
  CASE jsonb_typeof(j)
  WHEN 'object' THEN
    RETURN EXISTS (SELECT 1 FROM jsonb_each(j) e
      WHERE EXISTS (SELECT 1 FROM unnest(ids) i WHERE strpos(e.key, i) > 0)
         OR app.purge_json_mentions(e.value, ids));
  WHEN 'array' THEN
    RETURN EXISTS (SELECT 1 FROM jsonb_array_elements(j) e WHERE app.purge_json_mentions(e, ids));
  WHEN 'string' THEN
    RETURN EXISTS (SELECT 1 FROM unnest(ids) i WHERE strpos(j #>> '{}', i) > 0);
  ELSE
    RETURN false;
  END CASE;
END $$;

CREATE OR REPLACE FUNCTION app.purge_scrub_json(j jsonb, ids text[]) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE r jsonb;
BEGIN
  IF j IS NULL THEN RETURN NULL; END IF;
  IF jsonb_typeof(j) = 'object' THEN
    SELECT coalesce(jsonb_object_agg(e.key, app.purge_scrub_json(e.value, ids)), '{}'::jsonb)
      INTO r FROM jsonb_each(j) e
      WHERE NOT app.purge_pii_key(e.key)
        AND NOT app.purge_json_mentions(jsonb_build_object(e.key, NULL), ids)
        AND NOT (jsonb_typeof(e.value) = 'string' AND app.purge_json_mentions(e.value, ids));
    RETURN r;
  ELSIF jsonb_typeof(j) = 'array' THEN
    SELECT coalesce(jsonb_agg(app.purge_scrub_json(e.value, ids) ORDER BY e.ord), '[]'::jsonb)
      INTO r FROM jsonb_array_elements(j) WITH ORDINALITY e(value, ord)
      WHERE NOT (jsonb_typeof(e.value) = 'string' AND app.purge_json_mentions(e.value, ids));
    RETURN r;
  END IF;
  RETURN j;
END $$;

__OWNER__
-- 规定的匿名化 UPDATE：NEW 必须恰好等于由 OLD 推出的值
CREATE OR REPLACE FUNCTION app.purge_anonymize_ok(tbl text, o jsonb, n jsonb, uids uuid[])
RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE
  base text := regexp_replace(tbl, '_(p[0-9]{6}|default)$', '');
  ids text[];
  actor_hit boolean;
  target_hit boolean;
  detail_hit boolean;
  expected jsonb;
BEGIN
  IF base = 'app.audit_logs' THEN
    ids := app.purge_ref_ids(uids);
    actor_hit := coalesce((o->>'actor_id')::uuid = ANY (uids), false);
    target_hit := app.purge_target_ref(o->>'target_id', uids);
    detail_hit := app.purge_json_mentions(o->'detail', ids);
    IF NOT (actor_hit OR target_hit OR detail_hit) THEN RETURN false; END IF;
    expected := o || jsonb_build_object(
      'actor_id', CASE WHEN actor_hit THEN NULL ELSE o->'actor_id' END,
      'target_id', CASE WHEN target_hit THEN NULL ELSE o->'target_id' END,
      'detail', app.purge_scrub_json(o->'detail', ids),
      'ip_hash', CASE WHEN actor_hit OR (o->>'actor_id') IS NULL THEN NULL ELSE o->'ip_hash' END);
  ELSIF base = 'app.account_reviews' THEN
    actor_hit := coalesce((o->>'admin_id')::uuid = ANY (uids), false);
    target_hit := coalesce((o->>'user_id')::uuid = ANY (uids), false);
    IF NOT (actor_hit OR target_hit) THEN RETURN false; END IF;
    expected := o || jsonb_build_object(
      'admin_id', CASE WHEN actor_hit THEN NULL ELSE o->'admin_id' END,
      'user_id', CASE WHEN target_hit THEN NULL ELSE o->'user_id' END,
      'reason', NULL);
  ELSIF base = 'ops.data_licence_events' THEN
    IF NOT coalesce((o->>'user_id')::uuid = ANY (uids), false) THEN RETURN false; END IF;
    expected := o || jsonb_build_object('user_id', NULL, 'licence_id', NULL);
  ELSE
    RETURN false;
  END IF;
  RETURN n = expected;
END $$;

-- B1：purging 只能由 aia_maint 经 UPDATE 写入；写入后该行只能 DELETE
CREATE OR REPLACE FUNCTION app.guard_users_purging() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'purging' THEN
      RAISE EXCEPTION 'app.users：不允许以 status=purging 插入'
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status = 'purging' THEN
    RAISE EXCEPTION 'app.users：status=purging 的行只能删除，不能再修改'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'purging' AND current_user <> '__MAINT__' THEN
    RAISE EXCEPTION 'app.users：只有 __MAINT__ 角色可以写 status=purging（当前 %）', current_user
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_users_purging_guard
  BEFORE INSERT OR UPDATE ON app.users
  FOR EACH ROW EXECUTE FUNCTION app.guard_users_purging();

-- B1：按行延迟检查——本事务置为 purging 的那一行提交时必须已删除
CREATE OR REPLACE FUNCTION app.reject_purging_commit() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.users WHERE id = NEW.id) THEN
    RAISE EXCEPTION 'app.users：用户 % 置为 purging 后未在同一事务内删除，不允许提交', NEW.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_users_purging_not_committed ON app.users;
CREATE CONSTRAINT TRIGGER trg_users_purging_not_committed
  AFTER UPDATE OF status ON app.users
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW WHEN (NEW.status = 'purging')
  EXECUTE FUNCTION app.reject_purging_commit();
""".replace("__OWNER__", OWNER_FUNCTION).replace("__MAINT__", MAINT_ROLE)

OLD_FUNCTIONS = r"""
DROP TRIGGER IF EXISTS trg_users_purging_guard ON app.users;
DROP FUNCTION IF EXISTS app.guard_users_purging();
DROP TRIGGER IF EXISTS trg_users_purging_not_committed ON app.users;
CREATE OR REPLACE FUNCTION app.purge_pii_key(k text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT lower(k) ~ ('(^|_)(security_code|symbol|symbols|name|username|email|path|filename|file'
    || '|mask|masked|suffix|last4|amount|qty|quantity|price|cost|fee|fees|cash|balance'
    || '|market_value|user_agent|ip|apply_note|note)$')
$$;

CREATE OR REPLACE FUNCTION app.purge_row_owner(tbl text, o jsonb) RETURNS uuid
LANGUAGE plpgsql STABLE AS $$
DECLARE
  base text := regexp_replace(tbl, '_(p[0-9]{6}|default)$', '');
  r uuid;
BEGIN
  CASE base
  WHEN __DIRECT__ THEN
    RETURN (o->>'user_id')::uuid;
  WHEN 'app.broker_position_snapshots' THEN
    SELECT a.user_id INTO r FROM app.accounts a WHERE a.id = (o->>'account_id')::uuid;
  WHEN 'app.broker_position_snapshot_items' THEN
    SELECT a.user_id INTO r FROM app.broker_position_snapshots s
      JOIN app.accounts a ON a.id = s.account_id WHERE s.id = (o->>'snapshot_id')::uuid;
  WHEN 'app.daily_report_items' THEN
    SELECT d.user_id INTO r FROM app.daily_reports d WHERE d.id = (o->>'report_id')::uuid;
  WHEN 'app.plan_versions' THEN
    SELECT p.user_id INTO r FROM app.action_plans p WHERE p.id = (o->>'plan_id')::uuid;
  WHEN 'app.plan_conditions' THEN
    SELECT p.user_id INTO r FROM app.plan_versions v
      JOIN app.action_plans p ON p.id = v.plan_id WHERE v.id = (o->>'plan_version_id')::uuid;
  WHEN 'app.review_versions' THEN
    SELECT v.user_id INTO r FROM app.reviews v WHERE v.id = (o->>'review_id')::uuid;
  WHEN 'app.reason_status_events' THEN
    SELECT n.user_id INTO r FROM app.non_executable_reasons n WHERE n.id = (o->>'reason_id')::uuid;
  WHEN 'app.candidate_versions' THEN
    SELECT c.user_id INTO r FROM app.research_candidates c WHERE c.id = (o->>'candidate_id')::uuid;
  WHEN 'app.strategy_instance_events' THEN
    SELECT i.user_id INTO r FROM app.strategy_instances i WHERE i.id = (o->>'instance_id')::uuid;
  WHEN 'app.risk_control_settings_history' THEN
    SELECT coalesce((o->>'user_id')::uuid, s.user_id) INTO r FROM app.risk_control_settings s
      WHERE s.id = (o->>'setting_id')::uuid;
  WHEN 'app.candidate_signal_events' THEN
    SELECT s.user_id INTO r FROM app.candidate_signals s WHERE s.id = (o->>'signal_id')::uuid;
  ELSE
    RETURN NULL;
  END CASE;
  RETURN r;
END $$;

CREATE OR REPLACE FUNCTION app.purge_anonymize_ok(tbl text, o jsonb, n jsonb, uids uuid[])
RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE
  base text := regexp_replace(tbl, '_(p[0-9]{6}|default)$', '');
  actor_hit boolean;
  target_hit boolean;
  expected jsonb;
BEGIN
  IF base = 'app.audit_logs' THEN
    actor_hit := coalesce((o->>'actor_id')::uuid = ANY (uids), false);
    target_hit := app.purge_target_ref(o->>'target_id', uids);
    IF NOT (actor_hit OR target_hit) THEN RETURN false; END IF;
    expected := o || jsonb_build_object(
      'actor_id', CASE WHEN actor_hit THEN NULL ELSE o->'actor_id' END,
      'target_id', CASE WHEN target_hit THEN NULL ELSE o->'target_id' END,
      'detail', app.purge_scrub_json(o->'detail'),
      'ip_hash', CASE WHEN actor_hit OR (o->>'actor_id') IS NULL THEN NULL ELSE o->'ip_hash' END);
  ELSIF base = 'app.account_reviews' THEN
    actor_hit := coalesce((o->>'admin_id')::uuid = ANY (uids), false);
    target_hit := coalesce((o->>'user_id')::uuid = ANY (uids), false);
    IF NOT (actor_hit OR target_hit) THEN RETURN false; END IF;
    expected := o || jsonb_build_object(
      'admin_id', CASE WHEN actor_hit THEN NULL ELSE o->'admin_id' END,
      'user_id', CASE WHEN target_hit THEN NULL ELSE o->'user_id' END);
  ELSIF base = 'ops.data_licence_events' THEN
    IF NOT coalesce((o->>'user_id')::uuid = ANY (uids), false) THEN RETURN false; END IF;
    expected := o || jsonb_build_object('user_id', NULL, 'licence_id', NULL);
  ELSE
    RETURN false;
  END IF;
  RETURN n = expected;
END $$;

CREATE OR REPLACE FUNCTION app.reject_purging_commit() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.users WHERE status = 'purging') THEN
    RAISE EXCEPTION 'app.users：存在 status=purging 的行，不允许提交'
      '（删除用户数据必须在同一事务内删除用户行）'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_users_purging_not_committed
  AFTER INSERT OR UPDATE OF status ON app.users
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW WHEN (NEW.status = 'purging')
  EXECUTE FUNCTION app.reject_purging_commit();

DROP FUNCTION IF EXISTS app.purge_scrub_json(jsonb, text[]);
DROP FUNCTION IF EXISTS app.purge_json_mentions(jsonb, text[]);
DROP FUNCTION IF EXISTS app.purge_ref_ids(uuid[]);
""".replace("__DIRECT__", ", ".join(f"'{t}'" for t in DIRECT_OWNER_TABLES))


def upgrade() -> None:
    op.add_column(
        "data_snapshots",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="app",
    )
    op.add_column(
        "data_snapshots",
        sa.Column("licence_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="app",
    )
    op.create_foreign_key(
        op.f("fk_data_snapshots_user_id_users"),
        "data_snapshots",
        "users",
        ["user_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        op.f("fk_data_snapshots_licence_id_user_data_licences"),
        "data_snapshots",
        "user_data_licences",
        ["licence_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_index(
        "ix_data_snapshots_user_id",
        "data_snapshots",
        ["user_id"],
        schema="app",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_data_snapshots_licence_id",
        "data_snapshots",
        ["licence_id"],
        schema="app",
        postgresql_where=sa.text("licence_id IS NOT NULL"),
    )
    op.execute(NEW_FUNCTIONS)


def downgrade() -> None:
    op.execute(OLD_FUNCTIONS)
    op.drop_index("ix_data_snapshots_licence_id", table_name="data_snapshots", schema="app")
    op.drop_index("ix_data_snapshots_user_id", table_name="data_snapshots", schema="app")
    op.drop_constraint(
        op.f("fk_data_snapshots_licence_id_user_data_licences"),
        "data_snapshots",
        schema="app",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_data_snapshots_user_id_users"), "data_snapshots", schema="app", type_="foreignkey"
    )
    op.drop_column("data_snapshots", "licence_id", schema="app")
    op.drop_column("data_snapshots", "user_id", schema="app")
