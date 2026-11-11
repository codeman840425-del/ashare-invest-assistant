"""Bounded four-file Vitest timing diagnosis; never edits tests or timeout settings.

Raw logs/JSON stay in the caller's external output directory. A nonzero Vitest
exit, missing JSON, failed assertion or unhandled error makes this runner fail.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import itertools
import json
import os
import subprocess
import threading
import time
from pathlib import Path

FILES = (
    "src/pages/stock/t-f10.test.tsx",
    "src/pages/t-f03.test.tsx",
    "src/pages/t-a09.test.tsx",
    "src/pages/t-f22a.test.tsx",
)


def host_sample() -> dict[str, int]:
    """Only aggregate host counters; no process names, paths or environment."""
    if os.name != "nt":
        return {}

    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "page_total",
                "page_available",
                "virtual_total",
                "virtual_available",
                "extended",
            )
        ]

    memory = Memory()
    memory.length = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        return {}
    idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return {}
    return {
        "available_bytes": memory.available,
        "idle": idle.value,
        "total_cpu": kernel.value + user.value,
    }


def monitor(stop: threading.Event, samples: list[dict[str, int]]) -> None:
    while not stop.is_set():
        samples.append(host_sample())
        stop.wait(1)


def git_value(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_CONFIG_COUNT="0")
    return subprocess.check_output(["git", *args], cwd=repo, env=env, text=True).strip()


def run_case(
    node: Path,
    repo: Path,
    output: Path,
    label: str,
    files: tuple[str, ...],
    workers: int,
) -> dict:
    frontend = repo / "src/frontend"
    result_path = output / f"{label}.json"
    log_path = output / f"{label}.log"
    if result_path.exists() or log_path.exists():
        raise FileExistsError(
            f"Evidence already exists for {label}; choose a fresh output directory"
        )
    command = [
        str(node),
        str(frontend / "node_modules/vitest/vitest.mjs"),
        "run",
        *files,
        f"--maxWorkers={workers}",
        "--reporter=default",
        "--reporter=json",
        f"--outputFile.json={result_path}",
    ]
    stop = threading.Event()
    samples: list[dict[str, int]] = []
    sampler = threading.Thread(target=monitor, args=(stop, samples), daemon=True)
    sampler.start()
    started = time.monotonic()
    try:
        with log_path.open("wb") as log:
            # No shell, no timeout/retry overrides, no production proxy target.
            env = dict(os.environ, NO_COLOR="1")
            env.pop("VITE_API_PROXY", None)
            completed = subprocess.run(
                command,
                cwd=frontend,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
    finally:
        stop.set()
        sampler.join()
    elapsed = time.monotonic() - started
    data = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.exists()
        else {}
    )
    assertions = [
        {
            "file": Path(group["name"]).name,
            "name": item.get("fullName", item.get("title")),
            "status": item["status"],
            "duration_ms": item.get("duration"),
        }
        for group in data.get("testResults", [])
        for item in group.get("assertionResults", [])
    ]
    cpu = []
    for before, after in itertools.pairwise(samples):
        if before and after and after["total_cpu"] > before["total_cpu"]:
            total = after["total_cpu"] - before["total_cpu"]
            cpu.append(100 * (1 - (after["idle"] - before["idle"]) / total))
    memory = [sample["available_bytes"] for sample in samples if sample]
    # Vitest 5 JSON does not expose a numeric unhandled-error count.
    errors = data.get("numUnhandledErrors")
    unhandled_banner = "Vitest caught" in log_path.read_text(
        encoding="utf-8", errors="replace"
    )
    failed = data.get("numFailedTests", 0)
    ok = (
        completed.returncode == 0
        and bool(data)
        and data.get("success") is True
        and not unhandled_banner
    )
    summary = {
        "label": label,
        "workers": workers,
        "pool": "forks (Vitest default)",
        "files": list(files),
        "exit_code": completed.returncode,
        "success": ok,
        "elapsed_seconds": round(elapsed, 3),
        "passed": data.get("numPassedTests"),
        "failed": failed,
        "pending": data.get("numPendingTests"),
        "unhandled_errors": errors,
        "unhandled_error_banner_seen": unhandled_banner,
        "host_cpu_percent_max": round(max(cpu), 2) if cpu else None,
        "host_cpu_percent_mean": round(sum(cpu) / len(cpu), 2) if cpu else None,
        "host_available_bytes_min": min(memory) if memory else None,
        "assertions": assertions,
    }
    (output / f"{label}-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"{label}: exit={completed.returncode} passed={summary['passed']} "
        f"failed={failed} errors={errors} seconds={elapsed:.3f}",
        flush=True,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-sha", required=True)
    parser.add_argument("--repeat", type=int, default=2, choices=range(1, 4))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.is_relative_to(repo):
        parser.error("--output must be outside the worktree")
    # A docs/diagnostic-only descendant is allowed if the tested frontend tree is identical.
    expected = git_value(repo, "rev-parse", f"{args.frozen_sha}:src/frontend")
    actual = git_value(repo, "rev-parse", "HEAD:src/frontend")
    if expected != actual or git_value(
        repo, "status", "--porcelain", "--", "src/frontend"
    ):
        parser.error("frontend differs from the frozen commit")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    cases = [(f"four-w4-{i + 1}", FILES, 4) for i in range(args.repeat)]
    cases += [("four-w1", FILES, 1), ("pair-w2", (FILES[1], FILES[3]), 2)]
    cases += [(f"solo-{Path(file).stem}", (file,), 1) for file in FILES]
    for label, files, workers in cases:
        results.append(
            run_case(args.node.resolve(), repo, output, label, files, workers)
        )
    manifest = {
        "frozen_commit": args.frozen_sha,
        "diagnostic_head": git_value(repo, "rev-parse", "HEAD"),
        "frontend_tree": actual,
        "logical_cpus": os.cpu_count(),
        "node_version": subprocess.check_output(
            [str(args.node), "--version"], text=True
        ).strip(),
        "lock_sha256": hashlib.sha256(
            (repo / "src/frontend/pnpm-lock.yaml").read_bytes()
        ).hexdigest(),
        "note": "Bounded observations; cache is not cleared; repeated runs are warm, not independent cold samples. Host CPU cannot establish causality.",
        "runs": results,
    }
    (output / "matrix.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0 if all(row["success"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
