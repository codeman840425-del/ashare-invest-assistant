"""Atomic deletion retention and DB-clock binding expiry, private to ingest."""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA ingest_private;
        REVOKE ALL ON SCHEMA ingest_private FROM PUBLIC;
        CREATE TABLE ingest_private.mairui_gate_scopes (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          origin_licence_id uuid NOT NULL,
          detached_at timestamptz
        );
        CREATE TABLE ingest_private.mairui_gate_bindings (
          licence_id uuid PRIMARY KEY REFERENCES app.user_data_licences(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
          scope_id uuid NOT NULL REFERENCES ingest_private.mairui_gate_scopes(id),
          tag bytea NOT NULL,
          expires_at timestamptz
        );
        CREATE INDEX ix_mairui_gate_bindings_user_tag
          ON ingest_private.mairui_gate_bindings(user_id, tag);
        -- Existing role bootstrap grants all owned schemas. RLS remains a hard
        -- row barrier even if that broad grant is reapplied after this migration.
        ALTER TABLE ingest_private.mairui_gate_bindings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ingest_private.mairui_gate_scopes ENABLE ROW LEVEL SECURITY;
        CREATE POLICY gate_ingest_only ON ingest_private.mairui_gate_bindings
          USING(current_user='aia_ingest') WITH CHECK(current_user='aia_ingest');
        CREATE POLICY gate_ingest_only ON ingest_private.mairui_gate_scopes
          USING(current_user='aia_ingest') WITH CHECK(current_user='aia_ingest');

        CREATE FUNCTION ingest_private.prune_mairui_gate_bindings() RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
          DELETE FROM ingest_private.mairui_gate_bindings WHERE expires_at <= now();
          UPDATE ingest_private.mairui_gate_scopes s SET detached_at=COALESCE(s.detached_at,now())
          WHERE NOT EXISTS (
            SELECT 1 FROM ingest_private.mairui_gate_bindings b
            JOIN app.user_data_licences l ON l.id=b.licence_id
            WHERE b.scope_id=s.id AND l.deleted_at IS NULL
              AND (b.expires_at IS NULL OR b.expires_at>now())
          );
        END $$;
        REVOKE ALL ON FUNCTION ingest_private.prune_mairui_gate_bindings() FROM PUBLIC;

        CREATE FUNCTION ingest_private.mairui_gate_licence_deleted() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
          IF TG_OP='DELETE' THEN
            DELETE FROM ingest_private.mairui_gate_bindings WHERE licence_id=OLD.id;
          ELSIF NEW.deleted_at IS NOT NULL THEN
            UPDATE ingest_private.mairui_gate_bindings SET expires_at=LEAST(
              COALESCE(expires_at,'infinity'::timestamptz),
              CASE WHEN NEW.paused_until IS NOT NULL THEN NEW.paused_until
                   WHEN NEW.status IN ('ip_limited','quota_exceeded')
                        THEN NEW.deleted_at+interval '24 hours'
                   ELSE NEW.deleted_at END
            ) WHERE licence_id=NEW.id;
          END IF;
          PERFORM ingest_private.prune_mairui_gate_bindings();
          RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION ingest_private.mairui_gate_licence_deleted() FROM PUBLIC;
        CREATE TRIGGER mairui_gate_on_licence_deletion
          AFTER UPDATE OF deleted_at,paused_until,status OR DELETE
          ON app.user_data_licences FOR EACH ROW
          EXECUTE FUNCTION ingest_private.mairui_gate_licence_deleted();

        DO $$ BEGIN
          IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aia_ingest') THEN
            GRANT USAGE ON SCHEMA ingest_private TO aia_ingest;
            GRANT SELECT,INSERT,UPDATE,DELETE ON ingest_private.mairui_gate_bindings TO aia_ingest;
            GRANT SELECT,INSERT,UPDATE ON ingest_private.mairui_gate_scopes TO aia_ingest;
            GRANT EXECUTE ON FUNCTION ingest_private.prune_mairui_gate_bindings() TO aia_ingest;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS(SELECT 1 FROM ingest_private.mairui_gate_scopes)
             OR EXISTS(SELECT 1 FROM ingest_private.mairui_gate_bindings) THEN
            RAISE EXCEPTION 'mairui_gate_facts_require_authorized_archive';
          END IF;
        END $$;
        DROP TRIGGER mairui_gate_on_licence_deletion ON app.user_data_licences;
        DROP FUNCTION ingest_private.mairui_gate_licence_deleted();
        DROP FUNCTION ingest_private.prune_mairui_gate_bindings();
        DROP TABLE ingest_private.mairui_gate_bindings;
        DROP TABLE ingest_private.mairui_gate_scopes;
        DROP SCHEMA ingest_private;
    """)
