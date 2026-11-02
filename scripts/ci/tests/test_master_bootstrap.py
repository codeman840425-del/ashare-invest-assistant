"""T-A04：deploy/scripts/master-bootstrap.sh（主数据首次导入，手动步骤）。用假 compose.sh，不连库、不联网。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/master-bootstrap.sh"

FAKE = r"""#!/usr/bin/env bash
log="$FAKE_DIR/calls.log"
echo "ARGS $* MAIRUI=${MAIRUI_LICENCE+set}" >>"$log"
case "$1" in
  --get) echo fakeproj; exit 0 ;;
  exec)
    in="$(cat)"
    if [[ "$in" == *to_regclass* ]]; then
      [ "$FAKE_STATE" = no_table ] && echo "" || echo market.master_runs
    elif [[ "$in" == *EXISTS* ]]; then
      if [ -e "$FAKE_DIR/ran" ]; then echo "${FAKE_AFTER:-done}"; else echo "$FAKE_STATE"; fi
    fi
    exit "${FAKE_SQL_RC:-0}" ;;
  run)
    if [[ "$*" == *"--entrypoint python worker -c"* ]]; then exit "${FAKE_CLI_RC:-0}"; fi
    if [[ "$*" == *"worker python -m app.cli.master_bootstrap"* ]]; then touch "$FAKE_DIR/ran"; exit "${FAKE_RUN_RC:-0}"; fi
    exit 99 ;;
esac
exit 98
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    f = tmp_path / "compose.sh"
    f.write_text(FAKE, encoding="utf-8")
    f.chmod(0o755)
    return tmp_path


def _run(fake: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(fake),
        "XDG_RUNTIME_DIR": str(fake),
        "FAKE_DIR": str(fake),
        "AIA_MASTER_BOOTSTRAP_COMPOSE": str(fake / "compose.sh"),
        "MAIRUI_LICENCE": "fake-not-a-real-licence",
        "FAKE_STATE": "needed",
    }
    env.update(extra)
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)


def _calls(fake: Path) -> str:
    p = fake / "calls.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


@pytest.mark.parametrize(("state", "cli_rc", "want"), [("no_table", "0", 3), ("done", "0", 0), ("needed", "0", 10), ("needed", "1", 3)])
def test_check_exit_codes(fake: Path, state: str, cli_rc: str, want: int) -> None:
    r = _run(fake, "--check", FAKE_STATE=state, FAKE_CLI_RC=cli_rc)
    assert r.returncode == want, r.stderr
    assert "app.cli.master_bootstrap" not in _calls(fake).replace("find_spec('app.cli.master_bootstrap')", "")


def test_check_is_read_only(fake: Path) -> None:
    _run(fake, "--check")
    calls = _calls(fake)
    assert "python -m app.cli.master_bootstrap" not in calls
    assert not (fake / "ran").exists()


def test_run_requires_confirm_flag(fake: Path) -> None:
    r = _run(fake, "--run")
    assert r.returncode == 4 and "--confirm-network-fetch" in r.stderr
    assert _calls(fake) == ""


@pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS"])
def test_run_refused_in_ci(fake: Path, var: str) -> None:
    r = _run(fake, "--run", "--confirm-network-fetch", **{var: "true"})
    assert r.returncode == 4 and "CI" in r.stderr
    assert _calls(fake) == ""


def test_run_executes_once_when_needed(fake: Path) -> None:
    r = _run(fake, "--run", "--confirm-network-fetch")
    assert r.returncode == 0, r.stderr
    calls = _calls(fake)
    assert calls.count("python -m app.cli.master_bootstrap") == 1
    assert "--no-deps" in calls
    assert "fake-not-a-real-licence" not in r.stdout + r.stderr


def test_run_is_idempotent_when_done(fake: Path) -> None:
    r = _run(fake, "--run", "--confirm-network-fetch", FAKE_STATE="done")
    assert r.returncode == 0 and "跳过" in r.stderr
    assert "python -m app.cli.master_bootstrap" not in _calls(fake)


def test_run_not_ready_does_nothing(fake: Path) -> None:
    r = _run(fake, "--run", "--confirm-network-fetch", FAKE_STATE="no_table")
    assert r.returncode == 3
    assert "python -m app.cli.master_bootstrap" not in _calls(fake)
    r = _run(fake, "--run", "--confirm-network-fetch", FAKE_CLI_RC="1")
    assert r.returncode == 3 and "T-B52" in r.stderr
    assert "python -m app.cli.master_bootstrap" not in _calls(fake)


def test_run_fails_if_cli_fails_or_no_ok_row(fake: Path) -> None:
    r = _run(fake, "--run", "--confirm-network-fetch", FAKE_RUN_RC="1")
    assert r.returncode == 1
    (fake / "ran").unlink()
    r = _run(fake, "--run", "--confirm-network-fetch", FAKE_AFTER="needed")
    assert r.returncode == 1 and "视为失败" in r.stderr


def test_run_lock_prevents_concurrency(fake: Path) -> None:
    lock = fake / "aia-master-bootstrap-fakeproj.lock"
    with lock.open("w") as fh:
        holder = subprocess.Popen(["flock", "-x", str(lock), "sleep", "5"])
        try:
            import time

            time.sleep(0.3)
            r = _run(fake, "--run", "--confirm-network-fetch")
        finally:
            holder.kill()
            holder.wait()
    del fh
    assert r.returncode == 5 and "正在运行" in r.stderr
    assert "python -m app.cli.master_bootstrap" not in _calls(fake)


def test_usage_errors(fake: Path) -> None:
    assert _run(fake).returncode == 2
    assert _run(fake, "--check", "--run").returncode == 2
    assert _run(fake, "--bogus").returncode == 2


def test_no_automatic_trigger() -> None:
    """自动 up、compose 服务、CI 工作流都不得调用首次导入。"""
    paths = [REPO / "deploy/scripts/up.sh", REPO / "deploy/scripts/compose.sh"]
    paths += sorted((REPO / "deploy/compose").glob("*.y*ml"))
    paths += sorted((REPO / ".github/workflows").glob("*.y*ml"))
    for p in paths:
        text = p.read_text(encoding="utf-8")
        assert "master-bootstrap" not in text and "master_bootstrap" not in text, p
