"""review-6670b10：deploy/scripts/db-precheck-0017.sh（0017 升级前只读查违规行）与 up.sh 的调用。用假 psql，不连库。"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/db-precheck-0017.sh"
UP = REPO / "deploy/scripts/up.sh"
MIGRATION = REPO / "src/backend/migrations/versions/0017_t_b49_snapshot_purpose.py"

FAKE_PSQL = r"""#!/usr/bin/env bash
in="$(cat)"
echo "$in" >>"$FAKE_DIR/sql.log"
[ -n "${FAKE_FAIL:-}" ] && exit 3
case "$in" in
  *alembic_version*) echo "${FAKE_VER-0016}" ;;
  *"to_regclass('app.data_snapshots')"*) echo "${FAKE_TBL-app.data_snapshots}" ;;
  *"GROUP BY purpose"*) [ -n "${FAKE_BAD:-}" ] && printf '%b\n' "$FAKE_BAD" ;;
esac
exit 0
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    b = tmp_path / "bin"
    b.mkdir()
    (b / "psql").write_text(FAKE_PSQL, encoding="utf-8")
    (b / "psql").chmod(0o755)
    return tmp_path


def _run(fake: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": f"{fake / 'bin'}:{os.environ['PATH']}", "HOME": str(fake), "FAKE_DIR": str(fake),
           "AIA_PSQL_MODE": "direct", "PGDATABASE": "fakedb"}
    env.update(extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60)


def _sql(fake: Path) -> str:
    p = fake / "sql.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_clean_db_passes(fake: Path) -> None:
    r = _run(fake)
    assert r.returncode == 0 and "违规行 0" in r.stderr


def test_violations_stop(fake: Path) -> None:
    r = _run(fake, FAKE_BAD="plan=1\\nhorizon=2")
    assert r.returncode == 1
    assert "plan=1" in r.stderr and "horizon=2" in r.stderr and "不要升级到 0017" in r.stderr


@pytest.mark.parametrize("ver", ["0017", "0018", "0100"])
def test_already_at_or_after_0017_skips(fake: Path, ver: str) -> None:
    r = _run(fake, FAKE_VER=ver, FAKE_BAD="plan=1")
    assert r.returncode == 0 and "跳过" in r.stderr
    assert "GROUP BY purpose" not in _sql(fake)


def test_empty_db_and_missing_table(fake: Path) -> None:
    assert _run(fake, FAKE_VER="").returncode == 0
    assert _run(fake, FAKE_TBL="").returncode == 0


def test_query_error_is_2(fake: Path) -> None:
    assert _run(fake, FAKE_FAIL="1").returncode == 2


def test_all_queries_read_only(fake: Path) -> None:
    _run(fake, FAKE_BAD="plan=1")
    sql = _sql(fake)
    assert sql.count("BEGIN READ ONLY;") == 3 and sql.count("ROLLBACK;") == 3
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE|COMMIT)\b", sql, re.I)


def test_sql_matches_migration() -> None:
    if not MIGRATION.exists():
        pytest.skip("0017 迁移不在本检出")
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    want = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PRECHECK_SQL" for t in node.targets):
            want = ast.literal_eval(node.value)
    assert want, "迁移里找不到 PRECHECK_SQL"
    assert f'PRECHECK_SQL="{want}"' in SCRIPT.read_text(encoding="utf-8")


def test_up_runs_precheck_before_compose_up() -> None:
    text = UP.read_text(encoding="utf-8")
    i = text.index('"$HERE/db-precheck-0017.sh"')
    j = text.index('"$HERE/compose.sh" up ')
    assert i < j
    assert "exit 1" in text[i:j]
