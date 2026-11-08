# ruff: noqa: E501, S608
# Dynamic identifiers are fixed EXTRAS/static tuples, never caller input; values are bound.
"""T-A28 notification merge facts, no historical reference invention."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="app",
    )
    op.create_check_constraint("version_positive", "notifications", "version >= 1", schema="app")
    bind = op.get_bind()
    # T-A35/38: preserve every old row; unknown ownership is a refusal, not a DELETE.
    inspector = sa.inspect(bind)
    for table in ("signal_states", "signal_events", "intraday_universe"):
        op.add_column(
            table,
            sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema="app",
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_source_licence_id"),
            table,
            "user_data_licences",
            ["source_licence_id"],
            ["id"],
            source_schema="app",
            referent_schema="app",
        )
    for old in inspector.get_unique_constraints("signal_states", schema="app"):
        if old["column_names"] == ["security_code", "strategy_version_id", "params_hash"]:
            op.drop_constraint(
                op.f(str(old["name"])), "signal_states", schema="app", type_="unique"
            )
    op.create_unique_constraint(
        op.f("uq_signal_states_licence_key"),
        "signal_states",
        ["source_licence_id", "security_code", "strategy_version_id", "params_hash"],
        schema="app",
    )
    op.add_column(
        "signal_events",
        sa.Column(
            "input_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.data_snapshots.id"),
        ),
        schema="app",
    )
    op.add_column(
        "signal_events",
        sa.Column(
            "engine_policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.engine_policies.id"),
        ),
        schema="app",
    )
    op.add_column(
        "signal_events",
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True)),
        schema="app",
    )
    for col in ("params_hash", "rule_id"):
        op.add_column("signal_events", sa.Column(col, sa.Text()), schema="app")
    op.add_column(
        "signal_events",
        sa.Column(
            "legacy_binding_unknown", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        schema="app",
    )
    _restore_and_prove(bind)
    for table in ("signal_events", "signal_states", "intraday_universe"):
        if bind.execute(
            sa.text(f"SELECT EXISTS(SELECT 1 FROM app.{table} WHERE source_licence_id IS NULL)")
        ).scalar_one():
            raise RuntimeError("unproved_legacy_owner:" + table)
        op.alter_column(table, "source_licence_id", nullable=False, schema="app")
    old_pk = inspector.get_pk_constraint("intraday_universe", schema="app")
    op.drop_constraint(
        op.f(str(old_pk["name"])), "intraday_universe", schema="app", type_="primary"
    )
    op.create_primary_key(
        op.f("pk_intraday_universe"),
        "intraday_universe",
        ["trade_date", "source_licence_id", "security_code"],
        schema="app",
    )
    op.create_index(
        "uq_signal_events_shared_tick",
        "signal_events",
        [
            "source_licence_id",
            "security_code",
            "strategy_version_id",
            "params_hash",
            "rule_id",
            "tick_id",
        ],
        unique=True,
        schema="app",
        postgresql_where=sa.text("NOT legacy_binding_unknown"),
    )
    op.create_index(
        "uq_signal_events_user_tick",
        "signal_events",
        ["user_id", "security_code", "trigger_kind", "tick_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("NOT legacy_binding_unknown"),
    )
    op.add_column(
        "candidate_signals",
        sa.Column(
            "origin_signal_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.signal_events.id"),
        ),
        schema="app",
    )
    # Candidate bodies are partitioned by created_at: this global relation enforces
    # (instance,event) once without pretending a cross-partition index is possible.
    if sa.inspect(bind).has_table("intraday_candidate_refs_rollback", schema="app"):
        op.rename_table("intraday_candidate_refs_rollback", "intraday_candidate_refs", schema="app")
    else:
        _create_candidate_refs()
    op.add_column(
        "notifications",
        sa.Column("merged_count", sa.Integer(), nullable=False, server_default="1"),
        schema="app",
    )
    op.add_column(
        "notifications", sa.Column("updated_at", sa.DateTime(timezone=True)), schema="app"
    )
    op.add_column(
        "notifications",
        sa.Column(
            "refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        schema="app",
    )
    op.create_check_constraint(
        op.f("ck_notifications_merged_count"), "notifications", "merged_count >= 1", schema="app"
    )
    _restore_tail(bind)


def _create_candidate_refs() -> None:
    op.create_table(
        "intraday_candidate_refs",
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.strategy_instances.id"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.signal_events.id"),
            nullable=False,
        ),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True)),
        sa.PrimaryKeyConstraint("instance_id", "event_id"),
        schema="app",
    )


def _mutate(bind: sa.Connection, table: str, sql: str) -> None:
    # Transactional DDL exclusively locks these facts. Temporarily disable only
    # immutable/restricted-update guards, never constraints/ownership checks.
    names = (
        bind.execute(
            sa.text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid=to_regclass(:t) AND tgfoid IN ('app.reject_mutation()'::regprocedure,'app.restrict_update()'::regprocedure) AND NOT tgisinternal"
            ),
            {"t": "app." + table},
        )
        .scalars()
        .all()
    )
    if table not in EXTRAS:
        raise ValueError("migration_table_not_allowed")
    quote = bind.dialect.identifier_preparer.quote
    for name in names:
        bind.execute(sa.text(f"ALTER TABLE app.{quote(table)} DISABLE TRIGGER {quote(name)}"))
    bind.execute(sa.text(sql))
    for name in names:
        bind.execute(sa.text(f"ALTER TABLE app.{quote(table)} ENABLE TRIGGER {quote(name)}"))


EXTRAS = {
    "signal_events": [
        "source_licence_id",
        "input_snapshot_id",
        "engine_policy_id",
        "strategy_version_id",
        "params_hash",
        "rule_id",
        "legacy_binding_unknown",
    ],
    "signal_states": ["source_licence_id"],
    "intraday_universe": ["source_licence_id"],
    "candidate_signals": ["origin_signal_event_id"],
    "notifications": ["version", "merged_count", "updated_at", "refs"],
}


def _key(table: str, alias: str) -> str:
    if table == "intraday_universe":
        return f"{alias}.trade_date::text||'|'||{alias}.security_code"
    if table == "candidate_signals":
        return f"{alias}.id::text||'|'||extract(epoch from {alias}.created_at)::text"
    return f"{alias}.id::text"


def _restore(bind: sa.Connection, tables: list[str]) -> None:
    if not sa.inspect(bind).has_table("p2n06_rollback_0025", schema="app"):
        return
    for table in tables:
        fields = ",".join(f"{c}=v.{c}" for c in EXTRAS[table])
        sql = f"UPDATE app.{table} t SET {fields} FROM app.p2n06_rollback_0025 b CROSS JOIN LATERAL jsonb_populate_record(NULL::app.{table},b.payload) v WHERE b.table_name='{table}' AND b.row_key={_key(table, 't')}"
        _mutate(bind, table, sql)


def _restore_and_prove(bind: sa.Connection) -> None:
    import hashlib
    import json
    import uuid

    _restore(bind, ["signal_events", "signal_states", "intraday_universe"])
    rows = (
        bind.execute(
            sa.text(
                "SELECT id,scope,user_id,security_code,created_at,detail FROM app.signal_events WHERE source_licence_id IS NULL"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        detail = row["detail"] or {}
        reference = detail.get("input_snapshot_id") or detail.get("snapshot_id")
        try:
            reference = uuid.UUID(reference)
        except (TypeError, ValueError, AttributeError):
            raise RuntimeError("unowned_signal_events_require_ruling") from None
        source = (
            bind.execute(
                sa.text(
                    "SELECT s.id,s.user_id,s.licence_id,s.created_at,s.items,s.hash,l.user_id AS licence_owner FROM app.data_snapshots s JOIN app.user_data_licences l ON l.id=s.licence_id WHERE s.id=:id AND s.purpose='signal'"
                ),
                {"id": reference},
            )
            .mappings()
            .one_or_none()
        )
        if (
            source is None
            or source["user_id"] != source["licence_owner"]
            or source["created_at"] > row["created_at"]
            or (row["scope"] == "user" and row["user_id"] != source["user_id"])
        ):
            raise RuntimeError("unproved_legacy_snapshot_owner")
        raw = source["items"]
        digest = hashlib.sha256(
            json.dumps(
                raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
        if raw.get("security_code") != row["security_code"] or digest != source["hash"]:
            raise RuntimeError("unproved_legacy_snapshot_integrity")
        # Source owner is proven; historical instance binding is NOT reconstructed
        # from today's mutable instances. Unknown rows remain outside new projection.
        quote = bind.dialect.identifier_preparer.quote
        names = (
            bind.execute(
                sa.text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid='app.signal_events'::regclass AND tgfoid IN ('app.reject_mutation()'::regprocedure,'app.restrict_update()'::regprocedure) AND NOT tgisinternal"
                )
            )
            .scalars()
            .all()
        )
        for name in names:
            bind.execute(sa.text(f"ALTER TABLE app.signal_events DISABLE TRIGGER {quote(name)}"))
        bind.execute(
            sa.text(
                "UPDATE app.signal_events SET source_licence_id=:licence,input_snapshot_id=:source,legacy_binding_unknown=true WHERE id=:event"
            ),
            {"licence": source["licence_id"], "source": source["id"], "event": row["id"]},
        )
        for name in names:
            bind.execute(sa.text(f"ALTER TABLE app.signal_events ENABLE TRIGGER {quote(name)}"))


def _restore_tail(bind: sa.Connection) -> None:
    _restore(bind, ["candidate_signals", "notifications"])
    if sa.inspect(bind).has_table("p2n06_rollback_0025", schema="app"):
        # Dropping the preservation store only after every archived key is present
        # prevents a partially restored migration from discarding unreachable facts.
        for table in EXTRAS:
            missing = bind.execute(
                sa.text(
                    f"SELECT EXISTS(SELECT 1 FROM app.p2n06_rollback_0025 b WHERE b.table_name='{table}' AND NOT EXISTS(SELECT 1 FROM app.{table} t WHERE {_key(table, 't')}=b.row_key))"
                )
            ).scalar_one()
            if missing:
                raise RuntimeError("rollback_parent_missing:" + table)
        op.drop_table("p2n06_rollback_0025", schema="app")


def downgrade() -> None:
    bind = op.get_bind()
    # Old key collisions cannot be silently merged. This conditional failure is
    # transactional; 0026 refs have already been retained by rename, never DROP.
    for table, keys in [
        ("signal_states", "security_code,strategy_version_id,params_hash"),
        ("intraday_universe", "trade_date,security_code"),
    ]:
        if bind.execute(
            sa.text(f"SELECT EXISTS(SELECT 1 FROM app.{table} GROUP BY {keys} HAVING count(*)>1)")
        ).scalar_one():
            raise RuntimeError("old_unique_key_conflict:" + table)
    op.create_table(
        "p2n06_rollback_0025",
        sa.Column("table_name", sa.Text(), primary_key=True),
        sa.Column("row_key", sa.Text(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app.users.id")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        schema="app",
    )
    for table in EXTRAS:
        owner = "t.user_id" if table in {"candidate_signals", "notifications"} else "l.user_id"
        join = (
            ""
            if table in {"candidate_signals", "notifications"}
            else " JOIN app.user_data_licences l ON l.id=t.source_licence_id"
        )
        bind.execute(
            sa.text(
                f"INSERT INTO app.p2n06_rollback_0025 SELECT '{table}',{_key(table, 't')},{owner},to_jsonb(t) FROM app.{table} t{join}"
            )
        )
    for role in ("aia_api", "aia_ingest", "aia_maint"):
        if bind.execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:r)"), {"r": role}
        ).scalar_one():
            op.execute(f"REVOKE ALL ON app.p2n06_rollback_0025 FROM {role}")
    op.rename_table("intraday_candidate_refs", "intraday_candidate_refs_rollback", schema="app")
    op.drop_constraint(
        op.f("ck_notifications_merged_count"), "notifications", schema="app", type_="check"
    )
    op.drop_constraint(
        op.f("ck_notifications_version_positive"), "notifications", schema="app", type_="check"
    )
    op.drop_index("uq_signal_events_shared_tick", table_name="signal_events", schema="app")
    op.drop_index("uq_signal_events_user_tick", table_name="signal_events", schema="app")
    pk = sa.inspect(bind).get_pk_constraint("intraday_universe", schema="app")
    op.drop_constraint(op.f(str(pk["name"])), "intraday_universe", schema="app", type_="primary")
    for table, columns in EXTRAS.items():
        for col in columns:
            op.drop_column(table, col, schema="app")
    op.create_unique_constraint(
        op.f("uq_signal_states_security_code"),
        "signal_states",
        ["security_code", "strategy_version_id", "params_hash"],
        schema="app",
    )
    op.create_primary_key(
        op.f("pk_intraday_universe"),
        "intraday_universe",
        ["trade_date", "security_code"],
        schema="app",
    )
