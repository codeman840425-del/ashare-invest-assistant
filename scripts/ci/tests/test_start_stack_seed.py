"""T-O73c：start-stack.sh 在 db-roles 之后、启动 worker 之前跑 engine_policy seed。

用 stub 掉的 compose.sh / docker / db-precheck，不连库、不联网、不启真容器。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/wrapup/start-stack.sh"

FAKE_COMPOSE = r"""#!/usr/bin/env bash
log="$FAKE_DIR/compose.log"
echo "ARGS $*" >>"$log"
case "$1" in
  --resolve|--get) echo fake; exit 0 ;;
  stop) exit 0 ;;
  ps)
    if [ "${2:-}" = "-q" ]; then echo fakepg; else echo "fake-ps"; fi
    exit 0 ;;
  up)
    echo "UP $*" >>"$log"
    exit 0 ;;
  run)
    echo "RUN $*" >>"$log"
    # 不得覆盖默认 entrypoint
    if [[ "$*" == *"--entrypoint"* ]]; then echo "entrypoint-override" >&2; exit 99; fi
    if [[ "$*" != *"--rm"* ]] || [[ "$*" != *"--no-deps"* ]] || [[ "$*" != *"-T"* ]]; then
      echo "missing-run-flags" >&2; exit 99
    fi
    if [[ "$*" != *" worker "* ]] && [[ "$*" != *" worker" ]]; then
      echo "missing-worker" >&2; exit 99
    fi
    if [[ "$*" != *'python -m app.engine_policies --database-url "$DATABASE_URL"'* ]]; then
      echo "missing-seed-cmd" >&2; exit 99
    fi
    printf '%s' "${FAKE_SEED_OUT-}"
    printf '%s' "${FAKE_SEED_ERR-}" >&2
    exit "${FAKE_SEED_RC:-0}"
    ;;
esac
exit 98
"""

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "DOCKER $*" >>"$FAKE_DIR/docker.log"
cmd="$1"
shift
# docker info
if [ "$cmd" = "info" ]; then exit 0; fi
if [ "$cmd" != "exec" ]; then exit 0; fi
# skip -e KEY=val
while [ $# -gt 0 ]; do
  case "$1" in
    -e) shift 2 ;;
    *) break ;;
  esac
done
# remaining: container + command
if [[ "$*" == *alembic_version* ]]; then
  echo 'relation "alembic_version" does not exist' >&2
  exit 1
fi
exit 0
"""

FAKE_PRECHECK = r"""#!/usr/bin/env bash
echo "PRECHECK $*" >>"$FAKE_DIR/precheck.log"
exit 0
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    dest = tmp_path / "20260101T000000Z"
    dest.mkdir()
    (dest / "manifest.json").write_text("{}\n", encoding="utf-8")
    dump = dest / "aia.dump"
    dump.write_bytes(b"dump")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    compose = bindir / "compose.sh"
    compose.write_text(FAKE_COMPOSE, encoding="utf-8")
    compose.chmod(0o755)
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    pre = bindir / "db-precheck.sh"
    pre.write_text(FAKE_PRECHECK, encoding="utf-8")
    pre.chmod(0o755)
    return tmp_path


def _run(fake: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    dest = fake / "20260101T000000Z"
    env = {
        "PATH": str(fake / "bin") + os.pathsep + os.environ["PATH"],
        "HOME": str(fake),
        "XDG_RUNTIME_DIR": str(fake),
        "FAKE_DIR": str(fake),
        "COMPOSE": str(fake / "bin" / "compose.sh"),
        "WRAPUP_DB_PRECHECK": str(fake / "bin" / "db-precheck.sh"),
        "UP_WAIT_TIMEOUT": "1",
        "FAKE_SEED_OUT": "engine_policy_seed_inserted=1\n",
        "FAKE_SEED_ERR": "",
        "FAKE_SEED_RC": "0",
    }
    env.update(extra)
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            *args,
            "--backup-dir",
            str(dest),
            "--container",
            "fakepg",
            "--db",
            "aia",
            "--volume-prefix",
            "o69",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _compose_log(fake: Path) -> str:
    p = fake / "compose.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _receipt(fake: Path) -> str | None:
    p = fake / "20260101T000000Z" / "engine_policy_seed.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def _worker_up(log: str) -> bool:
    return any(("UP " in line and "worker" in line) for line in log.splitlines())


def _seed_run(log: str) -> bool:
    return any(line.startswith("RUN ") for line in log.splitlines())


@pytest.mark.parametrize("inserted", ["1", "0"])
def test_seed_inserted_continues_and_starts_worker(fake: Path, inserted: str) -> None:
    r = _run(fake, "--apply", FAKE_SEED_OUT=f"engine_policy_seed_inserted={inserted}\n")
    assert r.returncode == 0, r.stderr
    assert _receipt(fake) == f"engine_policy_seed_inserted={inserted}\n"
    log = _compose_log(fake)
    assert _seed_run(log)
    assert _worker_up(log)
    # seed RUN 出现在 worker UP 之前
    run_at = min(i for i, line in enumerate(log.splitlines()) if line.startswith("RUN "))
    up_at = min(i for i, line in enumerate(log.splitlines()) if "UP " in line and "worker" in line)
    assert run_at < up_at
    assert "--entrypoint" not in log
    assert "postgresql" not in r.stdout + r.stderr
    assert "PASSWORD" not in r.stdout + r.stderr


def test_hash_conflict_stops_without_starting_worker(fake: Path) -> None:
    r = _run(
        fake,
        "--apply",
        FAKE_SEED_OUT="",
        FAKE_SEED_ERR="ValueError: engine_policy_version_hash_conflict\n",
        FAKE_SEED_RC="1",
    )
    assert r.returncode != 0, r.stderr
    assert "engine_policy_version_hash_conflict" in r.stderr
    assert "不启动 worker" in r.stderr
    assert "不删除旧行" in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


def test_nonzero_rc_stops_without_starting_worker(fake: Path) -> None:
    r = _run(fake, "--apply", FAKE_SEED_OUT="", FAKE_SEED_ERR="boom\n", FAKE_SEED_RC="3")
    assert r.returncode != 0, r.stderr
    assert "退出码为 3" in r.stderr
    assert "不启动 worker" in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


@pytest.mark.parametrize(
    "out",
    ["", "not-a-result\n", "engine_policy_seed_inserted=2\n", "engine_policy_seed_inserted=1\nextra\n"],
)
def test_unparseable_output_stops_without_starting_worker(fake: Path, out: str) -> None:
    r = _run(fake, "--apply", FAKE_SEED_OUT=out, FAKE_SEED_RC="0")
    assert r.returncode != 0, r.stderr
    assert "无法解析" in r.stderr
    assert "不启动 worker" in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


def test_dry_run_prints_seed_and_does_not_execute(fake: Path) -> None:
    r = _run(fake)  # no --apply
    assert r.returncode == 0, r.stderr
    assert "engine_policy seed" in r.stderr
    assert "python -m app.engine_policies --database-url" in r.stderr
    assert "将要执行（未写入）" in r.stderr
    assert "已写入本轮收据" not in r.stderr
    assert _receipt(fake) is None
    assert _compose_log(fake) == ""
    assert not (fake / "20260101T000000Z" / "engine_policy_seed.txt").exists()
