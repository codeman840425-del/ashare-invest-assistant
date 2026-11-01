# ruff: noqa: S608  # 拼接的只有本模块常量里的表名/条件与 pg_catalog 里的表名；值全部绑定参数
"""删除用户数据 CLI（plan §7.3「删除用户数据 CLI 规则」，T-B16-core）。

用法::

    python -m app.cli delete-user-data --user-id <uuid>             # 默认 dry-run，只读
    python -m app.cli delete-user-data --user-id <uuid> --execute   # 需再输入完整 user-id 确认

规则（不设维护会话旁路：不用会话变量、不用 ``session_replication_role``、不用专用角色）：

- **数据状态门**（迁移 0011）：同一事务内「``users.status='purging'`` → 处理全部子表
  → 删除 users 行」。
  不可变表的触发器只对 purging 用户的行放行 DELETE / 规定的匿名化 UPDATE；可延迟约束触发器在提交时
  发现仍有 purging 行就报错，所以中途失败或忘删 users 行都提交不了。API 没有任何写 purging 的路径。
- **物理删除**：个人财务数据及其派生数据（持仓、成交、导入批次与解析行、证书含密文、画像、自选、
  策略实例、candidate_signals 全部分区、signal_events、建议及用户动作、计划草稿及确认、风险事件、
  风控设置及历史、claims、symbol_horizon_assessments、日报、通知、会话……见 :data:`STEPS`）；
  ``market.*`` 中带 ``source_licence_id`` 列的表按该用户证书删除
  （当前库内尚无此列，运行时动态发现）；
  对应 Redis 键在提交后删除。
- **匿名化保留**：``app.audit_logs``、``app.account_reviews``、``ops.data_licence_events``、
  ``ops.ingest_request_log``：指向该用户的 user_id/actor_id/target_id 置 NULL；detail 去掉 PII 键
  （``app.purge_scrub_json``）；ip_hash 置 NULL（库里只有 IP 的 HMAC，无法按 /24、/48 截断）；
  动作、时间、结果码、行数保留。触发器校验只改了这些列、且只改成规定值。
- **原始导入文件**：提交后删除 ``AIA_IMPORTS_DIR``（默认 ``/srv/aia/imports``）下属于该用户的文件；
  失败写入 ``ops.pending_file_purges``（path、attempts、last_error，无 user_id），下次运行先重试，
  dry-run 列出。
- 结束写一条审计 ``admin.user_data_deleted``，detail 只含各表行数。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import redis
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.engine import engine_for

AUDIT_ACTION: Final = "admin.user_data_deleted"
DEFAULT_IMPORTS_DIR: Final = "/srv/aia/imports"

# ---- 子查询（:uid = 目标用户；:lids = 该用户全部证书行 id，含软删；:llm_ids 见下） ----
ACC = "SELECT id FROM app.accounts WHERE user_id = :uid"
BATCH = "SELECT id FROM app.import_batches WHERE user_id = :uid"
SUGG = "SELECT id FROM app.suggestions WHERE user_id = :uid"
PLANS = "SELECT id FROM app.action_plans WHERE user_id = :uid"
PV = f"SELECT id FROM app.plan_versions WHERE plan_id IN ({PLANS})"
UID = "user_id = :uid"


@dataclass(frozen=True)
class Step:
    """一步：``action`` ∈ delete / anonymize / unlink（清除指针或指向该用户的引用）。"""

    table: str
    action: str
    where: str
    set_sql: str | None = None  # UPDATE 的 SET 子句（anonymize / unlink）
    label: str | None = None

    @property
    def name(self) -> str:
        return self.label or self.table


def _d(table: str, where: str = UID, label: str | None = None) -> Step:
    return Step(table, "delete", where, label=label)


def _u(table: str, col: str, where: str, label: str | None = None) -> Step:
    return Step(table, "unlink", where, f"{col} = NULL", label=label or f"{table}.{col}")


#: 匿名化（必须最先做：audit 的 target_ref 需要证书/画像行还在；data_licence_events 先断开证书）
ANONYMIZE: Final[tuple[Step, ...]] = (
    Step(
        "app.audit_logs",
        "anonymize",
        "actor_id = :uid OR app.purge_target_ref(target_id, ARRAY[:uid]::uuid[])",
        "actor_id = CASE WHEN actor_id = :uid THEN NULL ELSE actor_id END, "
        "target_id = CASE WHEN app.purge_target_ref(target_id, ARRAY[:uid]::uuid[]) "
        "THEN NULL ELSE target_id END, "
        "detail = app.purge_scrub_json(detail), "
        "ip_hash = CASE WHEN actor_id = :uid OR actor_id IS NULL THEN NULL ELSE ip_hash END",
    ),
    Step(
        "app.account_reviews",
        "anonymize",
        "user_id = :uid OR admin_id = :uid",
        "user_id = CASE WHEN user_id = :uid THEN NULL ELSE user_id END, "
        "admin_id = CASE WHEN admin_id = :uid THEN NULL ELSE admin_id END",
    ),
    Step("ops.data_licence_events", "anonymize", UID, "user_id = NULL, licence_id = NULL"),
    Step("ops.ingest_request_log", "anonymize", "licence_id = ANY (:lids)", "licence_id = NULL"),
)

#: 删除顺序：子表在前（外键全是 NO ACTION，不可延迟；环形指针先清空）
STEPS: Final[tuple[Step, ...]] = (
    _u("app.action_plans", "current_version_id", f"{UID} AND current_version_id IS NOT NULL"),
    _u(
        "app.research_candidates", "current_version_id", f"{UID} AND current_version_id IS NOT NULL"
    ),
    _u("app.reviews", "current_version_id", f"{UID} AND current_version_id IS NOT NULL"),
    _u(
        "app.suggestion_threads",
        "current_suggestion_id",
        f"{UID} AND current_suggestion_id IS NOT NULL",
    ),
    _d(
        "app.notification_deliveries",
        "notification_id IN (SELECT id FROM app.notifications WHERE user_id = :uid) "
        "OR binding_id IN (SELECT id FROM app.notification_channel_bindings WHERE user_id = :uid)",
    ),
    _d("app.notifications"),
    _d("app.notification_channel_bindings"),
    _d("app.notification_preferences"),
    _d("app.alerts"),
    _d("app.alert_rules"),
    _d("app.import_rows", f"batch_id IN ({BATCH})"),
    _d("app.import_files", f"batch_id IN ({BATCH})"),
    _d(
        "app.reconciliation_items",
        f"run_id IN (SELECT id FROM app.reconciliation_runs WHERE account_id IN ({ACC}))",
    ),
    _d("app.reconciliation_runs", f"account_id IN ({ACC})"),
    _d(
        "app.broker_position_snapshot_items",
        "snapshot_id IN (SELECT id FROM app.broker_position_snapshots "
        f"WHERE account_id IN ({ACC}))",
    ),
    _d("app.broker_position_snapshots", f"account_id IN ({ACC})"),
    _d(
        "app.daily_report_items",
        "report_id IN (SELECT id FROM app.daily_reports WHERE user_id = :uid)",
    ),
    _d("app.daily_reports"),
    _d("app.suggestion_user_actions"),
    _d("app.risk_events"),
    _d("app.suggestion_tracking", f"suggestion_id IN ({SUGG})"),
    _d("app.plan_draft_confirmations"),
    _d(
        "app.review_versions",
        "review_id IN (SELECT id FROM app.reviews WHERE user_id = :uid)",
    ),
    _d("app.reviews"),
    _d("app.trades"),
    _d("app.alert_rules", label="app.alert_rules (2nd pass)"),
    _d("app.plan_conditions", f"plan_version_id IN ({PV})"),
    _d("app.plan_versions", f"plan_id IN ({PLANS})"),
    _d("app.action_plans"),
    _d(
        "app.candidate_versions",
        "candidate_id IN (SELECT id FROM app.research_candidates WHERE user_id = :uid)",
    ),
    _d("app.research_candidates"),
    _d("app.plan_drafts"),
    _d(
        "app.candidate_signal_events",
        "signal_id IN (SELECT id FROM app.candidate_signals WHERE user_id = :uid)",
    ),
    _d("app.candidate_signals"),
    _d("app.suggestions"),
    _d("app.suggestion_threads"),
    _d("app.symbol_horizon_assessments"),
    _d(
        "app.llm_calls",
        "id = ANY (:llm_ids) "
        "AND NOT EXISTS (SELECT 1 FROM app.suggestions s WHERE s.llm_call_id = llm_calls.id "
        "AND s.user_id <> :uid) "
        "AND NOT EXISTS (SELECT 1 FROM app.daily_reports r WHERE r.llm_call_id = llm_calls.id "
        "AND r.user_id <> :uid)",
        label="app.llm_calls (只被该用户建议/日报引用的)",
    ),
    _d(
        "app.strategy_instance_events",
        "instance_id IN (SELECT id FROM app.strategy_instances WHERE user_id = :uid)",
    ),
    _d("app.strategy_instances"),
    _d("app.strategy_runs"),
    _d("app.strategy_tracking_stats"),
    _d("app.user_strategy_weights"),
    _d("app.user_signal_states"),
    _d(
        "app.reason_status_events",
        "reason_id IN (SELECT id FROM app.non_executable_reasons WHERE user_id = :uid)",
    ),
    _d("app.non_executable_reasons"),
    _d("app.signal_events"),
    _d("app.claim_links", "claim_id IN (SELECT id FROM app.claims WHERE user_id = :uid)"),
    _d("app.claims"),
    _d(
        "app.risk_control_settings_history",
        "user_id = :uid OR setting_id IN "
        "(SELECT id FROM app.risk_control_settings WHERE user_id = :uid)",
    ),
    _d("app.risk_control_settings"),
    _d("app.account_events", f"account_id IN ({ACC})"),
    _d("app.cash_movements", f"account_id IN ({ACC})"),
    _d("app.holdings", f"account_id IN ({ACC})"),
    _d("app.opening_positions", f"account_id IN ({ACC})"),
    _d("app.import_batches"),
    _d("app.import_mappings"),
    _d("app.accounts"),
    _d("app.watchlist_items"),
    _d("app.user_profiles"),
    _d("app.user_realtime_prefs"),
    _d("app.user_restrictions"),
    _d("app.login_attempts"),
    _d("app.entitlement_overrides"),
    _d("app.user_subscriptions"),
    _d("app.user_data_licence_holds"),
    # 证书行（含密文）放在 market 删除之后，见 run_purge
    # 其他行里指向该用户的引用（行本身不是该用户的数据）
    _u("app.users", "reviewed_by", "reviewed_by = :uid AND id <> :uid"),
    _u("app.invite_codes", "used_by", "used_by = :uid"),
    _u(
        "app.invite_codes",
        "bound_username",
        "bound_username = :username",
        label="app.invite_codes.bound_username",
    ),
    _u("app.user_subscriptions", "created_by", "created_by = :uid"),
    _u("app.entitlement_overrides", "created_by", "created_by = :uid"),
    _u("app.llm_providers", "created_by", "created_by = :uid"),
    _u("app.strategy_promotion_reviews", "reviewer_id", "reviewer_id = :uid"),
    _u("app.llm_strategy_drafts", "reviewer_id", "reviewer_id = :uid"),
)

LICENCES_STEP: Final = _d("app.user_data_licences")

#: 指向该用户、但本 CLI 不能处理的引用（不可变表或 NOT NULL）→ 拒绝执行，需人工/架构裁定
BLOCKERS: Final[tuple[tuple[str, str], ...]] = (
    ("app.invite_codes", "created_by = :uid"),
    ("app.invite_codes", "revoked_by = :uid"),
    ("app.llm_strategy_drafts", "requested_by = :uid"),
    ("app.prompt_templates", "created_by = :uid"),
    ("app.realtime_settings", "changed_by = :uid"),
    (
        "app.risk_control_settings_history",
        "changed_by = :uid AND user_id IS DISTINCT FROM :uid AND setting_id NOT IN "
        "(SELECT id FROM app.risk_control_settings WHERE user_id = :uid)",
    ),
    (
        "app.candidate_versions",
        "created_by = :uid AND candidate_id NOT IN "
        "(SELECT id FROM app.research_candidates WHERE user_id = :uid)",
    ),
    ("app.strategy_card_versions", "created_by = :uid"),
    ("app.strategy_versions", "published_by = :uid OR lifecycle_changed_by = :uid"),
    ("app.strategy_lifecycle_events", "actor_id = :uid"),
    (
        "app.strategy_instance_events",
        "actor_id = :uid AND instance_id NOT IN "
        "(SELECT id FROM app.strategy_instances WHERE user_id = :uid)",
    ),
    ("app.strategies", "owner_user_id = :uid"),
    ("app.strategy_cards", "owner_user_id = :uid"),
)

#: 本 CLI 已覆盖的、指向 app.users 的外键列；库里出现新的外键列 → 视为阻断（防表结构漂移）
HANDLED_FK: Final[frozenset[str]] = frozenset(
    {
        *(
            f"{t}.user_id"
            for t in (
                "app.account_reviews", "app.accounts", "app.claims", "app.entitlement_overrides",
                "app.import_mappings", "app.login_attempts", "app.non_executable_reasons",
                "app.notification_channel_bindings", "app.notification_preferences",
                "app.notifications", "app.risk_control_settings", "app.signal_events",
                "app.symbol_horizon_assessments", "app.user_profiles", "app.user_realtime_prefs",
                "app.user_restrictions", "app.user_signal_states", "app.user_subscriptions",
                "app.watchlist_items", "app.import_batches", "app.suggestion_threads",
                "app.daily_reports", "app.strategy_instances", "app.strategy_runs",
                "app.strategy_tracking_stats", "app.suggestions", "app.user_strategy_weights",
                "app.candidate_signals", "app.plan_drafts", "app.research_candidates",
                "app.action_plans", "app.plan_draft_confirmations", "app.reviews", "app.trades",
                "app.alert_rules", "app.risk_events", "app.suggestion_user_actions",
                "app.alerts", "app.user_data_licences", "ops.data_licence_events",
                "app.user_data_licence_holds",
            )
        ),
        "app.users.reviewed_by", "app.account_reviews.admin_id", "app.invite_codes.created_by",
        "app.invite_codes.used_by", "app.invite_codes.revoked_by",
        "app.llm_strategy_drafts.requested_by", "app.llm_strategy_drafts.reviewer_id",
        "app.strategies.owner_user_id", "app.strategy_cards.owner_user_id",
        "app.prompt_templates.created_by", "app.llm_providers.created_by",
        "app.candidate_versions.created_by", "app.strategy_card_versions.created_by",
        "app.realtime_settings.changed_by", "app.risk_control_settings_history.changed_by",
        "app.strategy_versions.published_by", "app.strategy_versions.lifecycle_changed_by",
        "app.strategy_lifecycle_events.actor_id", "app.strategy_instance_events.actor_id",
        "app.strategy_promotion_reviews.reviewer_id", "app.user_subscriptions.created_by",
        "app.entitlement_overrides.created_by",
    }
)  # fmt: skip


class PurgeRefusedError(Exception):
    """前置检查不通过（用户不存在、已在 purging、存在阻断引用）。"""


@dataclass
class Plan:
    user_id: uuid.UUID
    username: str
    role: str
    licence_ids: list[uuid.UUID]
    llm_ids: list[uuid.UUID]
    counts: list[tuple[str, str, int]]  # (action, name, rows)
    market_tables: list[str]
    blockers: list[tuple[str, int]]
    files: list[Path]
    pending: list[tuple[str, int, str | None]]


def _params(plan_or_uid: Any, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return extra | {"uid": plan_or_uid}


def _count(conn: Connection, table: str, where: str, params: dict[str, Any]) -> int:
    return int(
        conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params).scalar_one()
    )


def _market_licence_tables(conn: Connection) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT table_schema || '.' || table_name FROM information_schema.columns "
            "WHERE table_schema = 'market' AND column_name = 'source_licence_id' "
            "AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname = 'market') "
            "ORDER BY 1"
        )
    ).scalars()
    return list(rows)


def _unhandled_fk_refs(conn: Connection, uid: uuid.UUID) -> list[tuple[str, int]]:
    cols = conn.execute(
        text(
            "SELECT n.nspname || '.' || c.relname, a.attname "
            "FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = ANY (k.conkey) "
            "WHERE k.contype = 'f' AND k.confrelid = 'app.users'::regclass "
            "AND NOT c.relispartition ORDER BY 1, 2"
        )
    ).all()
    out = []
    for table, col in cols:
        if f"{table}.{col}" in HANDLED_FK:
            continue
        n = _count(conn, table, f"{col} = :uid", {"uid": uid})
        out.append((f"{table}.{col}（未纳入本 CLI 的新外键列）", n))
    return out


def imports_root() -> Path:
    return Path(os.environ.get("AIA_IMPORTS_DIR", DEFAULT_IMPORTS_DIR))


def _inside(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _user_files(conn: Connection, uid: uuid.UUID) -> list[Path]:
    root = imports_root()
    paths: list[Path] = []
    for sp in conn.execute(
        text(
            f"SELECT storage_path FROM app.import_files WHERE batch_id IN ({BATCH}) "
            "AND storage_path IS NOT NULL"
        ),
        {"uid": uid},
    ).scalars():
        p = Path(sp)
        if not p.is_absolute():
            p = root / p
        if _inside(root, p):
            paths.append(p)
    user_dir = root / str(uid)
    if user_dir not in paths:
        paths.append(user_dir)  # 约定的每用户目录（不存在则跳过）
    return paths


def build_plan(conn: Connection, uid: uuid.UUID) -> Plan:
    user = conn.execute(
        text("SELECT id, username, role, status FROM app.users WHERE id = :uid"), {"uid": uid}
    ).one_or_none()
    if user is None:
        raise PurgeRefusedError("用户不存在")
    if user.status == "purging":
        raise PurgeRefusedError(
            "用户已处于 purging（上一次运行未完成？该状态无法提交，应不会出现）"
        )
    lids = list(
        conn.execute(
            text("SELECT id FROM app.user_data_licences WHERE user_id = :uid"), {"uid": uid}
        ).scalars()
    )
    llm_ids = list(
        conn.execute(
            text(
                "SELECT llm_call_id FROM app.suggestions WHERE user_id = :uid "
                "AND llm_call_id IS NOT NULL UNION "
                "SELECT llm_call_id FROM app.daily_reports WHERE user_id = :uid "
                "AND llm_call_id IS NOT NULL"
            ),
            {"uid": uid},
        ).scalars()
    )
    p = {"uid": uid, "lids": lids, "llm_ids": llm_ids, "username": user.username}
    counts: list[tuple[str, str, int]] = []
    for st in ANONYMIZE:
        counts.append((st.action, st.name, _count(conn, st.table, st.where, p)))
    market = _market_licence_tables(conn)
    for t in market:
        counts.append(("delete", t, _count(conn, t, "source_licence_id = ANY (:lids)", p)))
    seen: set[str] = set()
    for st in (*STEPS, LICENCES_STEP):
        if st.name in seen:
            continue
        seen.add(st.name)
        counts.append((st.action, st.name, _count(conn, st.table, st.where, p)))
    blockers = [(f"{t} WHERE {w}", _count(conn, t, w, p)) for t, w in BLOCKERS]
    blockers += _unhandled_fk_refs(conn, uid)
    pending = [
        (r.path, int(r.attempts), r.last_error)
        for r in conn.execute(
            text(
                "SELECT path, attempts, last_error FROM ops.pending_file_purges ORDER BY created_at"
            )
        ).all()
    ]
    return Plan(
        user_id=uid,
        username=user.username,
        role=user.role,
        licence_ids=lids,
        llm_ids=llm_ids,
        counts=counts,
        market_tables=market,
        blockers=[b for b in blockers if b[1] > 0],
        files=_user_files(conn, uid),
        pending=pending,
    )


def run_purge(conn: Connection, plan: Plan) -> dict[str, int]:
    """在调用方的**单个事务**里执行；返回各表实际行数（写入审计 detail）。"""
    uid = plan.user_id
    p = {"uid": uid, "lids": plan.licence_ids, "llm_ids": plan.llm_ids, "username": plan.username}
    locked = conn.execute(
        text("SELECT status FROM app.users WHERE id = :uid FOR UPDATE"), {"uid": uid}
    ).scalar_one()
    if locked == "purging":
        raise PurgeRefusedError("用户已处于 purging")
    conn.execute(text("UPDATE app.users SET status = 'purging' WHERE id = :uid"), {"uid": uid})
    rows: dict[str, int] = {}

    def add(key: str, n: int) -> None:
        rows[key] = rows.get(key, 0) + n

    for st in ANONYMIZE:
        n = conn.execute(text(f"UPDATE {st.table} SET {st.set_sql} WHERE {st.where}"), p).rowcount
        add(f"anonymize:{st.table}", n)
    for t in _market_licence_tables(conn):
        n = conn.execute(text(f"DELETE FROM {t} WHERE source_licence_id = ANY (:lids)"), p).rowcount
        add(f"delete:{t}", n)
    for st in (*STEPS, LICENCES_STEP):
        if st.action == "delete":
            n = conn.execute(text(f"DELETE FROM {st.table} WHERE {st.where}"), p).rowcount
            add(f"delete:{st.table}", n)
        else:
            n = conn.execute(
                text(f"UPDATE {st.table} SET {st.set_sql} WHERE {st.where}"), p
            ).rowcount
            if n:
                add(f"{st.action}:{st.name}", n)
    n = conn.execute(text("DELETE FROM app.users WHERE id = :uid"), {"uid": uid}).rowcount
    add("delete:app.users", n)
    conn.execute(
        text(
            "INSERT INTO app.audit_logs (actor_id, actor_role, action, target_type, target_id, "
            "detail) VALUES (NULL, 'system', :a, 'user', NULL, CAST(:d AS jsonb))"
        ),
        {"a": AUDIT_ACTION, "d": _json({"rows": {k: v for k, v in rows.items() if v}})},
    )
    return rows


def _json(obj: object) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# ---- 提交后：文件与 Redis ----


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def retry_pending(engine: Engine, out: Callable[[str], None]) -> int:
    """先重试上次失败的文件删除；返回仍失败的条数。"""
    failed = 0
    with engine.begin() as conn:
        for pid, path in conn.execute(
            text("SELECT id, path FROM ops.pending_file_purges ORDER BY created_at FOR UPDATE")
        ).all():
            try:
                _remove(Path(path))
            except OSError as exc:
                failed += 1
                conn.execute(
                    text(
                        "UPDATE ops.pending_file_purges SET attempts = attempts + 1, "
                        "last_error = :e, last_attempt_at = now() WHERE id = :id"
                    ),
                    {"e": type(exc).__name__ + ": " + (exc.strerror or ""), "id": pid},
                )
            else:
                conn.execute(
                    text("DELETE FROM ops.pending_file_purges WHERE id = :id"), {"id": pid}
                )
    out(f"pending_file_purges 重试：仍失败 {failed} 条")
    return failed


def purge_files(engine: Engine, files: Iterable[Path]) -> tuple[int, int]:
    deleted = queued = 0
    for f in files:
        try:
            if not (f.exists() or f.is_symlink()):
                continue
            _remove(f)
            deleted += 1
        except OSError as exc:
            queued += 1
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO ops.pending_file_purges (path, attempts, last_error, "
                        "last_attempt_at) VALUES (:p, 1, :e, now()) ON CONFLICT (path) DO UPDATE "
                        "SET attempts = ops.pending_file_purges.attempts + 1, "
                        "last_error = EXCLUDED.last_error, last_attempt_at = now()"
                    ),
                    {"p": str(f), "e": type(exc).__name__ + ": " + (exc.strerror or "")},
                )
    return deleted, queued


def purge_redis(client: redis.Redis, plan: Plan) -> int:
    """删除该用户与其证书相关的 Redis 键与 ``ingest:requests`` 条目；返回删除数。"""
    removed = 0
    needles = [str(plan.user_id), *(str(x) for x in plan.licence_ids)]
    patterns = [f"*{n}*" for n in needles]
    patterns.append(
        "auth:lockout:" + hashlib.sha256(plan.username.encode("utf-8")).hexdigest() + "*"
    )
    for pat in patterns:
        for key in client.scan_iter(match=pat, count=500):
            removed += int(client.delete(key))
    stream = "ingest:requests"
    if client.exists(stream):
        ids: list[bytes | str] = []
        for entry_id, fields in client.xrange(stream) or []:
            vals = {
                (v.decode() if isinstance(v, bytes) else str(v)) for v in (fields or {}).values()
            }
            if entry_id is not None and any(n in v for v in vals for n in needles):
                ids.append(entry_id)
        if ids:
            removed += int(client.xdel(stream, *ids))
    return removed


# ---- 入口 ----


def _urls() -> tuple[str, str | None]:
    db = os.environ.get("DATABASE_URL")
    rd = os.environ.get("REDIS_URL")
    if not db:
        from app.config import get_settings

        s = get_settings()
        db = s.database_url.get_secret_value() if s.database_url is not None else None
        rd = rd or s.redis_url
    if not db:
        raise SystemExit("未配置 DATABASE_URL")
    return db, rd


def print_plan(plan: Plan, out: Callable[[str], None]) -> None:
    out(f"用户 {plan.user_id}（role={plan.role}）")
    out(f"{'动作':<10} {'表':<60} 行数")
    for action, name, n in plan.counts:
        out(f"{action:<10} {name:<60} {n}")
    if not plan.market_tables:
        out("market.*：当前没有带 source_licence_id 列的表（按证书取数的表建好后自动纳入）")
    out(
        f"原始导入文件候选：{sum(1 for f in plan.files if f.exists())} 个"
        f"（根目录 {imports_root()}）"
    )
    out(f"ops.pending_file_purges：{len(plan.pending)} 条")
    for path, attempts, err in plan.pending:
        out(f"  - {path}（attempts={attempts}，last_error={err}）")
    if plan.blockers:
        out("阻断（存在本 CLI 不能处理的引用，--execute 会拒绝）：")
        for what, n in plan.blockers:
            out(f"  - {what}: {n}")


def main(argv: list[str] | None = None, *, confirm: Callable[[str], str] = input) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli delete-user-data")
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--execute", action="store_true", help="真正执行（默认 dry-run）")
    args = ap.parse_args(argv)
    try:
        uid = uuid.UUID(args.user_id)
    except ValueError:
        print("--user-id 不是合法 uuid", file=sys.stderr)
        return 2
    db_url, redis_url = _urls()
    engine = engine_for(db_url)

    def out(s: str) -> None:
        print(s)

    try:
        with engine.connect() as conn:
            plan = build_plan(conn, uid)
            conn.rollback()
    except PurgeRefusedError as exc:
        print(f"拒绝：{exc}", file=sys.stderr)
        return 1
    print_plan(plan, out)
    if not args.execute:
        out("dry-run：未做任何修改。加 --execute 执行。")
        return 0
    if plan.blockers:
        print("拒绝执行：存在阻断引用（见上），需先人工处理或裁定。", file=sys.stderr)
        return 1
    typed = confirm(f"不可恢复。请输入完整 user-id 确认删除 {uid}：").strip()
    if typed != str(uid):
        print("确认不匹配，已取消。", file=sys.stderr)
        return 1
    retry_pending(engine, out)
    try:
        with engine.begin() as conn:
            plan = build_plan(conn, uid)  # 事务内重新取（锁在 run_purge 内）
            if plan.blockers:
                raise PurgeRefusedError("存在阻断引用")
            rows = run_purge(conn, plan)
    except PurgeRefusedError as exc:
        print(f"拒绝：{exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        # 整个事务已回滚（含 purging 状态）；只输出数据库错误首行，不回显绑定参数
        msg = str(getattr(exc, "orig", exc)).splitlines()[0]
        print(f"执行失败，已整体回滚：{type(exc).__name__}: {msg}", file=sys.stderr)
        return 1
    out("已提交：" + _json({k: v for k, v in rows.items() if v}))
    rc = 0
    deleted, queued = purge_files(engine, plan.files)
    out(f"原始导入文件：删除 {deleted}，失败入队 {queued}")
    if queued:
        rc = 3
    if redis_url:
        try:
            n = purge_redis(redis.Redis.from_url(redis_url, socket_timeout=5), plan)
            out(f"Redis：删除 {n} 个键/条目")
        except redis.RedisError as exc:
            print(f"Redis 清理失败（数据库已提交）：{type(exc).__name__}", file=sys.stderr)
            rc = 3
    else:
        out("Redis：未配置 REDIS_URL，跳过")
    return rc
