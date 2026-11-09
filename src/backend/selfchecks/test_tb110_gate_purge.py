# ruff: noqa: S101
"""T-A73 / T-B110: 0030 gate purge helpers — offline static checks."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]
MIG = ROOT / "src/backend/migrations/versions/0030_ta73_purge_gate_facts.py"


def test_0030_file_pins_and_does_not_touch_0029_objects() -> None:
    text = MIG.read_text(encoding="utf-8")
    assert 'revision = "0030"' in text
    assert 'down_revision = "0029"' in text
    assert "ops.gate_user_refs" in text
    assert "ops.purge_user_gate_facts" in text
    assert "SECURITY DEFINER" in text
    assert "search_path" in text
    assert "REVOKE ALL ON FUNCTION ops.gate_user_refs" in text
    assert "REVOKE ALL ON FUNCTION ops.purge_user_gate_facts" in text
    assert "GRANT EXECUTE ON FUNCTION ops.gate_user_refs(uuid) TO aia_maint" in text
    assert "GRANT EXECUTE ON FUNCTION ops.purge_user_gate_facts(uuid) TO aia_maint" in text
    assert "gate_purge_requires_purging_user" in text
    assert "gate_scope_shared" in text
    assert "DROP FUNCTION IF EXISTS ops.purge_user_gate_facts" in text
    assert "ALTER TABLE" not in text


def test_migration_heads_single_0030() -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0030"]


def test_cli_excludes_ingest_private_fk_scan_and_allowlists_gate_trigger() -> None:
    cli = (ROOT / "src/backend/app/cli/delete_user_data.py").read_text(encoding="utf-8")
    assert cli.count("n.nspname <> 'ingest_private'") == 2
    assert "mairui_gate_on_licence_deletion" in cli
    assert "ingest_private.mairui_gate_licence_deleted" in cli
    assert "ops.gate_user_refs" in cli
    assert "ops.purge_user_gate_facts" in cli
    # purge must appear before licence deletion in run_purge
    purge_at = cli.index("SELECT bindings, scopes FROM ops.purge_user_gate_facts")
    licence_at = cli.index("st = LICENCES_STEP")
    assert purge_at < licence_at
