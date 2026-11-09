"""T-A73 M6: maint-only helpers to count/purge ingest_private gate facts."""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = depends_on = None


def upgrade() -> None:
    # New functions only; do not alter 0029 objects or rows (T-A73 §2.2).
    op.execute(
        """
        CREATE FUNCTION ops.gate_user_refs(p_user uuid)
        RETURNS TABLE(bindings bigint, scopes bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
          SELECT
            (
              SELECT count(*)::bigint
              FROM ingest_private.mairui_gate_bindings b
              WHERE b.user_id = p_user
            ),
            (
              SELECT count(*)::bigint
              FROM ingest_private.mairui_gate_scopes s
              WHERE s.id IN (
                SELECT b.scope_id
                FROM ingest_private.mairui_gate_bindings b
                WHERE b.user_id = p_user
              )
                 OR s.origin_licence_id IN (
                SELECT l.id FROM app.user_data_licences l WHERE l.user_id = p_user
              )
            );
        $$;
        REVOKE ALL ON FUNCTION ops.gate_user_refs(uuid) FROM PUBLIC;
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aia_maint') THEN
            GRANT EXECUTE ON FUNCTION ops.gate_user_refs(uuid) TO aia_maint;
          END IF;
        END $$;

        CREATE FUNCTION ops.purge_user_gate_facts(p_user uuid)
        RETURNS TABLE(bindings bigint, scopes bigint)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
          scope_ids uuid[];
          v_bindings bigint;
          v_scopes bigint;
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM app.users u WHERE u.id = p_user AND u.status = 'purging'
          ) THEN
            RAISE EXCEPTION 'gate_purge_requires_purging_user';
          END IF;

          SELECT coalesce(array_agg(DISTINCT s.id), ARRAY[]::uuid[])
          INTO scope_ids
          FROM ingest_private.mairui_gate_scopes s
          WHERE s.id IN (
              SELECT b.scope_id
              FROM ingest_private.mairui_gate_bindings b
              WHERE b.user_id = p_user
            )
             OR s.origin_licence_id IN (
              SELECT l.id FROM app.user_data_licences l WHERE l.user_id = p_user
            );

          IF EXISTS (
            SELECT 1
            FROM ingest_private.mairui_gate_bindings b
            WHERE b.scope_id = ANY (scope_ids)
              AND b.user_id IS DISTINCT FROM p_user
          ) THEN
            RAISE EXCEPTION 'gate_scope_shared';
          END IF;

          DELETE FROM ingest_private.mairui_gate_bindings WHERE user_id = p_user;
          GET DIAGNOSTICS v_bindings = ROW_COUNT;

          DELETE FROM ingest_private.mairui_gate_scopes WHERE id = ANY (scope_ids);
          GET DIAGNOSTICS v_scopes = ROW_COUNT;

          RETURN QUERY SELECT v_bindings, v_scopes;
        END $$;
        REVOKE ALL ON FUNCTION ops.purge_user_gate_facts(uuid) FROM PUBLIC;
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aia_maint') THEN
            GRANT EXECUTE ON FUNCTION ops.purge_user_gate_facts(uuid) TO aia_maint;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS ops.purge_user_gate_facts(uuid);
        DROP FUNCTION IF EXISTS ops.gate_user_refs(uuid);
        """
    )
