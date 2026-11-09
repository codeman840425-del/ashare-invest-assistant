"""T-R39 negative: nongit + authority files; control (no pyc) PASS; with pyc → tracking_unknown.

Temp tree only (does not modify the repo). Copies docs/strategies plus the
authority paths check_horizons reads outside strategies (docs/plan.md,
docs/api-contract.md). Control group must exit 0 under normal and -O; then a
planted .pyc must exit≠0 with tracking_unknown in the message. Explicit
require/fail (no assert). Offline; no network; no credentials.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRATEGIES = HERE.parent  # docs/strategies
REPO = STRATEGIES.parents[1]  # repository root (…/docs/strategies → parents[1])
AUTHORITY_RELS = (
    "docs/plan.md",
    "docs/api-contract.md",
)


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


def _build_nongit_tree(dest_root: Path) -> Path:
    dest = dest_root / "docs" / "strategies"
    shutil.copytree(
        STRATEGIES,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for rel in AUTHORITY_RELS:
        src = REPO / rel
        require(src.is_file(), f"missing authority source {rel}")
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    require(not (dest_root / ".git").exists(), "temp tree must not be a git repo")
    return dest


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="t-r39-nongit-") as td:
        dest_root = Path(td) / "repo"
        dest = _build_nongit_tree(dest_root)

        control = {}
        for optimize in (False, True):
            r = _run_checker(dest, optimize=optimize)
            require(
                r.returncode == 0,
                f"control(no pyc) optimize={optimize} expected exit=0, got {r.returncode}; "
                f"stderr={ (r.stderr or '')[-400:] }",
            )
            require(
                '"result": "PASS"' in r.stdout or '"result":"PASS"' in r.stdout,
                f"control missing PASS: {r.stdout[-200:]}",
            )
            control["O" if optimize else "normal"] = {"exit": r.returncode}

        plant = dest / "__pycache__" / "_tr39_nongit_plant.cpython-313.pyc"
        plant.parent.mkdir(parents=True, exist_ok=True)
        plant.write_bytes(b"\0" * 16)

        experiment = {}
        for optimize in (False, True):
            r = _run_checker(dest, optimize=optimize)
            require(
                r.returncode != 0,
                f"experiment(with pyc) optimize={optimize} expected nonzero, got {r.returncode}",
            )
            err = (r.stderr or "") + (r.stdout or "")
            require(
                "tracking_unknown" in err,
                f"experiment optimize={optimize} missing tracking_unknown: {err[-500:]}",
            )
            experiment["O" if optimize else "normal"] = {
                "exit": r.returncode,
                "has_tracking_unknown": True,
            }

    out = {
        "result": "PASS",
        "case": "nongit_pyc_tracking_unknown_vs_control",
        "authorities_copied": list(AUTHORITY_RELS),
        "control_no_pyc": control,
        "experiment_with_pyc": experiment,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
