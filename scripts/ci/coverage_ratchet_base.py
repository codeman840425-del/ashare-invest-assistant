#!/usr/bin/env python3
"""Freeze a trusted base measurement, never the PR's own editable baseline.

Only the first approved pre-ratchet main commit uses the reviewed 4c02 counts.
Later baselines use validated main push artifacts. Only main events may recover
through a bounded first-parent history; PR events remain exact-base.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from coverage_ratchet import BOOTSTRAP_BASE, bootstrap_record, validate_record

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = "scripts/ci/coverage-baseline.json"
LIMIT = 8 * 1024 * 1024
MAX_FALLBACK_ANCESTORS = 50


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            target.remove_header("Authorization")
        return target


def base_identity(event: dict, env: dict) -> tuple[str, str]:
    repo = env["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    kind = env["GITHUB_EVENT_NAME"]
    if kind == "pull_request":
        base = event["pull_request"]["base"]
        if base["repo"]["full_name"] != repo or base["ref"] != "main":
            raise ValueError("Only this repository's trusted main base is accepted")
        sha = base["sha"]
    elif kind == "push" and env["GITHUB_REF"] == "refs/heads/main":
        sha = event["before"]
    elif kind == "workflow_dispatch" and env["GITHUB_REF"] == "refs/heads/main":
        sha = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True).strip()
    else:
        raise ValueError("Unsupported coverage baseline context")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or sha == "0" * 40:
        raise ValueError("Missing trusted base commit")
    return repo, sha


def api_reader(repo: str):
    opener = urllib.request.build_opener(SafeRedirect())
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("Missing Actions read token")

    def get(path: str, *, binary=False):
        if not path.startswith("/actions/"):
            raise ValueError("Unexpected API path")
        request = urllib.request.Request("https://api.github.com/repos/" + repo + path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        with opener.open(request, timeout=30) as response:
            data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("Baseline artifact exceeds bound")
        return data if binary else json.loads(data)
    return get


def read_artifact(data: bytes, sha: str, run_id: int, attempt: int) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        expected = "coverage-ratchet-measurement.json"
        if names.count(expected) != 1 or any(".." in path_parts(n) for n in names):
            raise ValueError("Unexpected measurement archive")
        entry = archive.getinfo(expected)
        if entry.file_size > LIMIT:
            raise ValueError("Measurement exceeds bound")
        record = validate_record(json.loads(archive.read(entry)))
    if (record.get("commit") != sha or record.get("run_id") != str(run_id)
            or record.get("attempt") != str(attempt) or record.get("ratchet_passed") is not True):
        raise ValueError("Artifact does not belong to exact trusted base run")
    record["source"] = {"kind": "trusted-main-push-artifact", "commit": sha,
                        "run_id": run_id, "attempt": attempt}
    return record


def path_parts(name: str):
    return name.replace("\\", "/").split("/")


class MeasurementPending(ValueError):
    """Only an existing exact-main push may justify waiting; never a fallback."""

    def __init__(self, sha: str, run_id: int):
        self.sha = sha
        self.run_id = run_id
        super().__init__(f"Exact main measurement pending: base={sha}, run={run_id}")


class MeasurementUnavailable(ValueError):
    """A known main head lacks a usable, validated main push measurement."""


def _freeze_exact(repo: str, sha: str, get, *, unavailable=ValueError) -> dict:
    # Keep PR selection, trust checks and failure behavior exact. Main recovery
    # classifies only missing/invalid measurement data, never git or API failures.
    exists = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=ROOT,
                            capture_output=True, check=False)
    if exists.returncode:
        raise ValueError("Trusted base commit is not present in fetched history")
    policy = subprocess.run(["git", "show", sha + ":" + POLICY_PATH], cwd=ROOT,
                            capture_output=True, check=False)
    if policy.returncode:
        if sha != BOOTSTRAP_BASE:
            raise ValueError("Trusted base has no ratchet measurement policy")
        record = bootstrap_record()
        record["source"] = record["source"] | {"base_commit": sha}
        return record
    runs = get("/actions/workflows/ci.yml/runs?event=push&branch=main&status=completed&head_sha="
               + sha + "&per_page=100")["workflow_runs"]
    runs = [r for r in runs if r["head_sha"] == sha and r["head_branch"] == "main"
            and r["event"] == "push" and r["status"] == "completed"
            and r["repository"]["full_name"] == repo]
    if not runs:
        active = get("/actions/workflows/ci.yml/runs?event=push&branch=main&head_sha="
                     + sha + "&per_page=100")["workflow_runs"]
        active = [r for r in active if r["head_sha"] == sha and r["head_branch"] == "main"
                  and r["event"] == "push" and r["status"] in {"queued", "in_progress", "waiting", "pending", "requested"}
                  and r["repository"]["full_name"] == repo]
        if active:
            raise MeasurementPending(sha, max(int(r["id"]) for r in active))
        raise unavailable("No completed exact-base main measurement run")
    run = max(runs, key=lambda r: (r["id"], r["run_attempt"]))
    artifacts = get("/actions/runs/" + str(run["id"]) + "/artifacts?per_page=100")["artifacts"]
    name = "coverage-ratchet-" + str(run["id"]) + "-" + str(run["run_attempt"])
    selected = [a for a in artifacts if a["name"] == name and not a["expired"]]
    if len(selected) != 1:
        raise unavailable("Missing, expired or ambiguous exact-base measurement")
    data = get("/actions/artifacts/" + str(selected[0]["id"]) + "/zip", binary=True)
    try:
        return read_artifact(data, sha, run["id"], run["run_attempt"])
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        if unavailable is ValueError:
            raise
        raise unavailable("Invalid exact-base main push measurement") from exc


def freeze(repo: str, sha: str, get, *, allow_fallback: bool = False) -> dict:
    if not allow_fallback:
        return _freeze_exact(repo, sha, get)
    requested = sha
    for skipped in range(MAX_FALLBACK_ANCESTORS + 1):
        try:
            record = _freeze_exact(repo, sha, get, unavailable=MeasurementUnavailable)
        except MeasurementPending:
            if skipped == 0:
                raise  # Retain the existing wait for this head's active push.
        except MeasurementUnavailable:
            pass
        else:
            if skipped == 0:
                return record  # Including the original exact bootstrap behavior.
            if record["source"]["kind"] != "trusted-main-push-artifact":
                break  # Never reset a missing chain to bootstrap counts.
            record["source"]["fallback"] = {
                "requested_base_commit": requested, "skipped_heads": skipped,
                "ancestor_limit": MAX_FALLBACK_ANCESTORS,
            }
            return record
        if skipped == MAX_FALLBACK_ANCESTORS:
            break
        parent = subprocess.run(["git", "rev-parse", "--verify", sha + "^1"],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        if parent.returncode:
            break
        sha = parent.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid first-parent commit identity")
    raise MeasurementUnavailable(
        "No usable trusted main push measurement within "
        f"{MAX_FALLBACK_ANCESTORS} first-parent ancestors")


def wait_for_base(repo: str, sha: str, get, timeout: int, *, allow_fallback: bool = False) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if allow_fallback:
                return freeze(repo, sha, get, allow_fallback=True)
            return freeze(repo, sha, get)
        except MeasurementPending as pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            print(f"Waiting for existing trusted main run {pending.run_id}; base={sha}", flush=True)
            time.sleep(min(15, remaining))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-for-main-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.wait_for_main_seconds <= 1800:
        parser.error("--wait-for-main-seconds must be between 0 and 1800")
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        repo, sha = base_identity(event, os.environ)
        get = api_reader(repo)
        if (os.environ["GITHUB_EVENT_NAME"] in {"push", "workflow_dispatch"}
                and os.environ.get("GITHUB_REF") == "refs/heads/main"):
            record = wait_for_base(repo, sha, get, args.wait_for_main_seconds,
                                   allow_fallback=True)
        else:
            record = wait_for_base(repo, sha, get, args.wait_for_main_seconds)
        if args.output.exists():
            raise ValueError("Refuse to replace a frozen baseline")
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        source = record["source"]
        selected = source.get("commit", sha)
        print("Frozen coverage baseline: " + selected + "; source=" + source["kind"])
        if "fallback" in source:
            print("Recovered requested base: " + sha
                  + "; skipped_heads=" + str(source["fallback"]["skipped_heads"]))
        return 0
    except MeasurementPending as pending:
        print("::error title=coverage-ratchet::" + str(pending))
        return 1
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.SubprocessError):
        print("::error title=coverage-ratchet::Trusted base measurement unavailable or invalid")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
