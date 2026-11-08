# ruff: noqa: E501
"""T-A34/35/38: frozen owned projections and shared-event purge ownership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0027"
down_revision = "0026"
branch_labels = depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Existing deployed 0026 did not run the amended 0025. Make the new flag
    # additive here too, without pretending old mutable instance matches are history.
    if "legacy_binding_unknown" not in {
        c["name"] for c in sa.inspect(bind).get_columns("signal_events", schema="app")
    }:
        op.add_column(
            "signal_events",
            sa.Column(
                "legacy_binding_unknown", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            schema="app",
        )
    keys = {
        "uq_signal_events_shared_tick": [
            "source_licence_id",
            "security_code",
            "strategy_version_id",
            "params_hash",
            "rule_id",
            "tick_id",
        ],
        "uq_signal_events_user_tick": ["user_id", "security_code", "trigger_kind", "tick_id"],
    }
    for constraint in sa.inspect(bind).get_unique_constraints("signal_events", schema="app"):
        if constraint["column_names"] in keys.values():
            op.drop_constraint(
                op.f(str(constraint["name"])), "signal_events", schema="app", type_="unique"
            )
    names = {i["name"] for i in sa.inspect(bind).get_indexes("signal_events", schema="app")}
    for name, columns in keys.items():
        if name not in names:
            op.create_index(
                name,
                "signal_events",
                columns,
                unique=True,
                schema="app",
                postgresql_where=sa.text("NOT legacy_binding_unknown"),
            )
    if sa.inspect(bind).has_table("signal_event_projections_rollback", schema="app"):
        op.rename_table(
            "signal_event_projections_rollback", "signal_event_projections", schema="app"
        )
    else:
        # No historical full matching-set receipt existed before T-A34. Preserve
        # explicit candidate/notification refs, but do not invent a frozen set.
        op.execute("ALTER TABLE app.signal_events DISABLE TRIGGER trg_signal_events_immutable")
        op.execute(
            "UPDATE app.signal_events SET legacy_binding_unknown=true WHERE NOT legacy_binding_unknown"
        )
        op.execute("ALTER TABLE app.signal_events ENABLE TRIGGER trg_signal_events_immutable")
        op.create_table(
            "signal_event_projections",
            sa.Column(
                "event_id",
                pg.UUID(as_uuid=True),
                sa.ForeignKey("app.signal_events.id"),
                primary_key=True,
            ),
            sa.Column(
                "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("app.users.id"), primary_key=True
            ),
            sa.Column(
                "instance_id", pg.UUID(as_uuid=True), sa.ForeignKey("app.strategy_instances.id")
            ),
            sa.Column("instance_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
            sa.Column("candidate_signal_id", pg.UUID(as_uuid=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            schema="app",
        )
        op.execute(
            "CREATE TRIGGER signal_event_projection_immutable BEFORE UPDATE OR DELETE ON app.signal_event_projections FOR EACH ROW EXECUTE FUNCTION app.reject_mutation()"
        )
    op.execute("""CREATE OR REPLACE FUNCTION app.validate_signal_event_projection() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE owner uuid;
    BEGIN
      SELECT l.user_id INTO owner FROM app.signal_events e JOIN app.user_data_licences l ON l.id=e.source_licence_id
      WHERE e.id=NEW.event_id AND NOT e.legacy_binding_unknown AND (e.scope='shared' OR e.user_id=l.user_id);
      IF owner IS NULL OR owner IS DISTINCT FROM NEW.user_id THEN RAISE EXCEPTION 'projection_owner_mismatch'; END IF;
      IF NEW.instance_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.strategy_instances i WHERE i.id=NEW.instance_id AND i.user_id=owner) THEN RAISE EXCEPTION 'projection_instance_owner'; END IF;
      IF EXISTS(SELECT 1 FROM unnest(NEW.instance_ids) x WHERE NOT EXISTS(SELECT 1 FROM app.strategy_instances i WHERE i.id=x AND i.user_id=owner)) OR cardinality(NEW.instance_ids)>20 THEN RAISE EXCEPTION 'projection_instances_invalid'; END IF;
      IF NEW.candidate_signal_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.candidate_signals c WHERE c.id=NEW.candidate_signal_id AND c.user_id=owner AND c.instance_id=NEW.instance_id AND c.origin_signal_event_id=NEW.event_id) THEN RAISE EXCEPTION 'projection_candidate_mismatch'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "DROP TRIGGER IF EXISTS signal_event_projection_owner ON app.signal_event_projections"
    )
    op.execute(
        "CREATE TRIGGER signal_event_projection_owner BEFORE INSERT ON app.signal_event_projections FOR EACH ROW EXECUTE FUNCTION app.validate_signal_event_projection()"
    )
    op.execute("ALTER FUNCTION app.purge_row_owner(text,jsonb) RENAME TO purge_row_owner_pre0027")
    op.execute("""CREATE FUNCTION app.purge_row_owner(tbl text,o jsonb) RETURNS uuid LANGUAGE plpgsql STABLE AS $$
    DECLARE r uuid;
    BEGIN
      IF tbl='app.signal_event_projections' THEN RETURN (o->>'user_id')::uuid; END IF;
      IF tbl='app.signal_events' THEN
        SELECT user_id INTO r FROM app.user_data_licences WHERE id=(o->>'source_licence_id')::uuid;
        IF o->>'scope'='user' AND (o->>'user_id')::uuid IS DISTINCT FROM r THEN RETURN NULL; END IF;
        RETURN r;
      END IF;
      RETURN app.purge_row_owner_pre0027(tbl,o);
    END $$""")
    # Narrow inherited default ACL, never elevate a worker/ingest role.
    for role in ("aia_ingest", "aia_api"):
        if bind.execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:r)"), {"r": role}
        ).scalar_one():
            op.execute(
                f"REVOKE {'ALL' if role == 'aia_ingest' else 'UPDATE,DELETE'} ON app.signal_event_projections FROM {role}"
            )


def downgrade() -> None:
    # Retain immutable projection facts under a non-runtime name, like 0026 refs.
    op.execute("DROP TRIGGER signal_event_projection_owner ON app.signal_event_projections")
    op.execute("DROP FUNCTION app.validate_signal_event_projection()")
    op.rename_table("signal_event_projections", "signal_event_projections_rollback", schema="app")
    op.execute("DROP FUNCTION app.purge_row_owner(text,jsonb)")
    op.execute("ALTER FUNCTION app.purge_row_owner_pre0027(text,jsonb) RENAME TO purge_row_owner")
