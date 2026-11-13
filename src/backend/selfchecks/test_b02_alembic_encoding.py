# ruff: noqa: S101, ANN401
"""Exercise locale-sensitive Alembic readers and lineage guards without a database."""

from __future__ import annotations

from configparser import ConfigParser
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db import migration_check


@pytest.mark.parametrize("codec", ["ascii", "cp936", "cp1252", "utf-8"])
def test_b02_alembic_entrypoints_work_with_legacy_locale_readers(
    monkeypatch: pytest.MonkeyPatch, codec: str
) -> None:
    original_read = ConfigParser.read

    def locale_read(
        parser: ConfigParser, filenames: Any, encoding: str | None = None
    ) -> list[str]:
        return original_read(parser, filenames, encoding=codec)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("read-only migration commands attempted database access")

    monkeypatch.setattr(ConfigParser, "read", locale_read)
    monkeypatch.setattr(migration_check, "engine_for", forbidden)
    script = migration_check.script_directory()
    assert migration_check.require_single_head(script) == "0034"
    assert "0021" not in {revision.revision for revision in script.walk_revisions()}
    output = StringIO()
    command.heads(Config(str(migration_check.BACKEND / "alembic.ini"), stdout=output))
    head_lines = output.getvalue().strip().splitlines()
    assert len(head_lines) == 1
    assert head_lines[0].startswith("0034 ")
    assert head_lines[0].endswith("(head)")
    # Startup without a configured database still runs the same read-only lineage check.
    migration_check.check_startup(SimpleNamespace(database_url=None))


def test_b02_multiple_heads_remain_rejected_before_database_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    for revision, parent in [("a", None), ("b", "a"), ("c", "a")]:
        (versions / f"{revision}.py").write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\n", encoding="utf-8"
        )

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("multiple migration heads reached database access")

    monkeypatch.setattr(migration_check, "script_directory", lambda: ScriptDirectory(str(tmp_path)))
    monkeypatch.setattr(migration_check, "engine_for", forbidden)
    with pytest.raises(migration_check.MigrationLineageError, match="MIGRATION_HEADS_NOT_UNIQUE"):
        migration_check.check_startup(SimpleNamespace(database_url=None))
