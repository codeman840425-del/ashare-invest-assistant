"""Explicit offline job: python -m app.replay --user UUID --database tb70_... --socket ...

No Settings/.env/credential reads. Only use a dedicated networkless PostgreSQL.
Existing user required; prints only the resulting simulated snapshot identifier.
"""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import URL, create_engine

from app.replay.baseline import load


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=uuid.UUID, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    if not args.database.startswith("tb70_") or not args.socket.startswith("/tmp/tb70-"):  # noqa: S108
        parser.error("only dedicated tb70_ database / tb70- UNIX socket accepted")
    engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username="postgres",
            database=args.database,
            query={"host": args.socket},
        )
    )
    try:
        with engine.begin() as conn:
            snapshot_id = load(conn, args.user, app_env="test")
        print(f"模拟回放 snapshot_id={snapshot_id}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
