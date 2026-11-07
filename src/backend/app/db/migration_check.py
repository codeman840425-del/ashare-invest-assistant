"""T-A14 read-only mainline guard. Never stamps, repairs or downgrades a database."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.engine import engine_for

BACKEND = Path(__file__).resolve().parents[2]


class MigrationLineageError(RuntimeError):
    """Safe schema-identity error; no connection URLs or credentials."""


def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def require_single_head(script: ScriptDirectory) -> str:
    heads = script.get_heads()
    if len(heads) != 1:
        raise MigrationLineageError(
            "MIGRATION_HEADS_NOT_UNIQUE: expected exactly one mainline head"
        )
    return str(heads[0])


def require_database_mainline(
    conn: Connection, script: ScriptDirectory, *, allow_empty: bool = False
) -> None:
    require_single_head(script)
    exists = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar_one()
    versions = (
        conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
        if exists
        else []
    )
    if not versions:
        if allow_empty:
            return
        raise MigrationLineageError("DATABASE_SCHEMA_UNINITIALIZED: migrate before startup")
    mainline = {revision.revision for revision in script.walk_revisions()}
    if len(versions) != 1 or any(version not in mainline for version in versions):
        safe = [
            str(v) if str(v).isascii() and str(v).isalnum() and len(str(v)) <= 40 else "<invalid>"
            for v in versions
        ]
        raise MigrationLineageError(
            "DATABASE_REVISION_NOT_MAINLINE: "
            + ",".join(safe)
            + "; stop; no automatic stamp/downgrade"
        )


def check_startup(settings: Settings) -> None:
    script = script_directory()
    require_single_head(script)
    if settings.database_url is None:
        return
    engine = engine_for(settings.database_url.get_secret_value())
    try:
        with engine.connect() as conn:
            require_database_mainline(conn, script)
    except SQLAlchemyError as exc:
        raise MigrationLineageError(
            "DATABASE_REVISION_CHECK_FAILED: " + type(exc).__name__
        ) from None
    finally:
        engine.dispose()


def main() -> None:
    print(require_single_head(script_directory()) + " (single mainline head)")


if __name__ == "__main__":
    main()
