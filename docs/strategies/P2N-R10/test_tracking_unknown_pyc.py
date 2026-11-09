"""T-R39 negative: non-git tree + .pyc → tracking_unknown → exit≠0 (T-A80 L-1).

Copies docs/strategies into a temp directory without .git, drops an unregistered
.pyc, runs check_horizons under normal and -O. Expects non-zero exit and
tracking_unknown in the failure message. Also records the no-pyc result in the
same non-git tree (may fail for missing repo-level authority paths such as
docs/plan.md — reported, not required to PASS). Offline; no network.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRATEGIES = HERE.parent  # docs/strategies


def fail(msg: object = "") -> None:
    """Explicit failure that survives python -O (unlike assert)."""
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)


def _run_checker(strategies_dir: Path, optimize: bool) -> subprocess.CompletedProcess:
    checker = strategies_dir / "P2N-R10" / "check_horizons.py"
    cmd = ["python3", "-O", str(checker)] if optimize else ["python3", str(checker)]
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="t-r39-nongit-") as td:
        td_path = Path(td)
        # Layout: <td>/repo/docs/strategies/... so ROOT=parents[2] of checker is <td>/repo
        dest_root = td_path / "repo"
        dest = dest_root / "docs" / "strategies"
        shutil.copytree(
            STRATEGIES,
            dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        require(not (dest_root / ".git").exists(), "temp tree must not be a git repo")
        plant = dest / "__pycache__" / "_tr39_nongit_plant.cpython-313.pyc"
        plant.parent.mkdir(parents=True, exist_ok=True)
        plant.write_bytes(b"\0" * 16)

        with_pyc = {}
        for optimize in (False, True):
            r = _run_checker(dest, optimize=optimize)
            require(r.returncode != 0, f"with_pyc optimize={optimize} expected nonzero, got {r.returncode}")
            err = (r.stderr or "") + (r.stdout or "")
            require(
                "tracking_unknown" in err,
                f"with_pyc optimize={optimize} missing tracking_unknown: {err[-500:]}",
            )
            with_pyc["O" if optimize else "normal"] = {
                "exit": r.returncode,
                "has_tracking_unknown": True,
            }

        plant.unlink()
        no_pyc = {}
        for optimize in (False, True):
            r = _run_checker(dest, optimize=optimize)
            err = ((r.stderr or "") + (r.stdout or ""))[-400:]
            no_pyc["O" if optimize else "normal"] = {
                "exit": r.returncode,
                "stderr_tail": err,
                "note": "non-git strategies-only tree may miss docs/plan.md authorities",
            }

    out = {
        "result": "PASS",
        "case": "nongit_pyc_tracking_unknown",
        "git_rc_probe": {
            "in_repo_untracked_expected": 1,
            "non_repo_expected": 128,
            "tracked_expected": 0,
        },
        "with_pyc": with_pyc,
        "nongit_no_pyc": no_pyc,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
