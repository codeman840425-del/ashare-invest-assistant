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
    old_events = bind.execute(sa.text("SELECT count(*) FROM app.signal_events")).scalar_one()
    if old_events:
        raise RuntimeError(f"unowned_signal_events_require_ruling: count={old_events}")
    # Derived legacy state is explicitly rebuildable; never assign a guessed owner.
    for table in ("signal_states", "intraday_universe"):
        count = bind.execute(sa.text(f"SELECT count(*) FROM app.{table}")).scalar_one()  # noqa: S608 - fixed table allowlist
        if count:
            import warnings

            warnings.warn(f"rebuild_derived_{table}: count={count}", stacklevel=2)
        bind.execute(sa.text(f"DELETE FROM app.{table}"))  # noqa: S608 - fixed table allowlist
    inspector = sa.inspect(bind)
    for table in ("signal_states", "signal_events", "intraday_universe"):
        op.add_column(
            table,
            sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            op.drop_constraint(op.f(old["name"]), "signal_states", schema="app", type_="unique")
    op.create_unique_constraint(
        op.f("uq_signal_states_licence_key"),
        "signal_states",
        ["source_licence_id", "security_code", "strategy_version_id", "params_hash"],
        schema="app",
    )
    old_pk = inspector.get_pk_constraint("intraday_universe", schema="app")
    op.drop_constraint(op.f(old_pk["name"]), "intraday_universe", schema="app", type_="primary")
    op.create_primary_key(
        op.f("pk_intraday_universe"),
        "intraday_universe",
        ["trade_date", "source_licence_id", "security_code"],
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
    for col, typ in [
        ("strategy_version_id", postgresql.UUID(as_uuid=True)),
        ("params_hash", sa.Text()),
        ("rule_id", sa.Text()),
    ]:
        op.add_column("signal_events", sa.Column(col, typ), schema="app")
    op.create_unique_constraint(
        op.f("uq_signal_events_shared_tick"),
        "signal_events",
        [
            "source_licence_id",
            "security_code",
            "strategy_version_id",
            "params_hash",
            "rule_id",
            "tick_id",
        ],
        schema="app",
    )
    op.create_unique_constraint(
        op.f("uq_signal_events_user_tick"),
        "signal_events",
        ["user_id", "security_code", "trigger_kind", "tick_id"],
        schema="app",
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


def downgrade() -> None:
    raise RuntimeError("P2N06 ownership downgrade requires an explicit data-preservation plan")
