"""Coverage policy counterexamples use synthetic counts, no services or network."""
import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import check_coverage as check
import coverage_ratchet as ratchet
import coverage_ratchet_base as loader
import pytest


def test_bootstrap_exact_score_passes_below_old_goals():
    base = deepcopy(ratchet.bootstrap_record())
    errors, rows = ratchet.compare(base["counts"], base, base["minimums"])
    assert not errors
    assert [r["status"] for r in rows[-2:]] == ["N/A", "N/A"]
    assert rows[0]["covered"] == 15571 and rows[0]["statements"] == 22926
    assert rows[3]["required_ratio"] == rows[3]["effective_minimum"] == [353, 436]


@pytest.mark.parametrize("scope", ["total", "domain", "importing", "signals"])
def test_one_covered_line_loss_fails_even_above_integer_floor(scope):
    base = deepcopy(ratchet.bootstrap_record())
    counts = deepcopy(base["counts"])
    counts[scope][0] -= 1
    errors, _ = ratchet.compare(counts, base, base["minimums"])
    assert any(scope + ": exact coverage decreased" in e for e in errors)


def test_changing_denominator_compares_exact_fraction_and_reports_delta():
    base = deepcopy(ratchet.bootstrap_record())
    counts = deepcopy(base["counts"])
    counts["total"][1] += 1
    errors, rows = ratchet.compare(counts, base, base["minimums"])
    assert errors and rows[0]["denominator_delta"] == 1
    counts["total"] = [value * 2 for value in base["counts"]["total"]]
    errors, rows = ratchet.compare(counts, base, base["minimums"])
    assert not errors and rows[0]["denominator_delta"] == 22926


def test_successful_improvement_becomes_next_exact_floor():
    base = deepcopy(ratchet.bootstrap_record())
    improved = deepcopy(base)
    improved["counts"]["total"][0] += 10
    assert not ratchet.compare(improved["counts"], base, base["minimums"])[0]
    assert ratchet.compare(base["counts"], improved, improved["minimums"])[0]


def policy_file(tmp_path, base):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"bootstrap": deepcopy(ratchet.BOOTSTRAP),
                                "selection": ratchet.SELECTION,
                                "minimums": base["minimums"]}))
    return path


@pytest.mark.parametrize("change", ["floor", "bootstrap", "selection", "previous_floor"])
def test_pr_policy_cannot_lower_base_or_rewrite_seed(tmp_path, change):
    base = deepcopy(ratchet.bootstrap_record())
    path = policy_file(tmp_path, base)
    policy = json.loads(path.read_text())
    if change == "floor":
        policy["minimums"]["total"] = 66
    elif change == "bootstrap":
        policy["bootstrap"]["counts"]["total"][0] -= 1
    elif change == "selection":
        policy["selection"] = {"directories": ["tests/backend"]}
    else:
        base["minimums"]["total"] = 68
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        ratchet.load_policy(path, base)


def test_minimum_can_rise_but_measurement_must_meet_it(tmp_path):
    base = deepcopy(ratchet.bootstrap_record())
    path = policy_file(tmp_path, base)
    policy = json.loads(path.read_text())
    policy["minimums"]["total"] = 68
    path.write_text(json.dumps(policy))
    floors = ratchet.load_policy(path, base)
    assert floors["total"] == 68
    assert ratchet.compare(base["counts"], base, floors)[0]


def test_zero_scopes_are_na_new_scope_is_measured_not_fake_100():
    base = deepcopy(ratchet.bootstrap_record())
    counts = deepcopy(base["counts"])
    counts["advice"] = [0, 10]
    errors, rows = ratchet.compare(counts, base, base["minimums"])
    assert errors and rows[-2]["newly_active"] and rows[-2]["status"] == "fail"
    counts["advice"] = [7, 10]
    assert not ratchet.compare(counts, base, base["minimums"])[0]
    counts["domain"] = [0, 0]
    assert ratchet.compare(counts, base, base["minimums"])[0]


@pytest.mark.parametrize("payload", [{}, {"files": {}}, {"files": {"app/x.py": {
    "summary": {"covered_lines": True, "num_statements": 1}}},
    "totals": {"covered_lines": 1, "num_statements": 1}}])
def test_missing_or_fabricated_counts_fail_closed(tmp_path, payload):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload))
    with pytest.raises((ValueError, KeyError)):
        ratchet.measured(path)


def test_cli_missing_measurement_is_nonzero_not_default_pass(tmp_path):
    base = deepcopy(ratchet.bootstrap_record())
    path = tmp_path / "base.json"
    path.write_text(json.dumps(base))
    empty = tmp_path / "nondet.json"
    empty.write_text(json.dumps({"schema": "aia-coverage-nondet-lines-v1", "files": []}))
    assert check.main([str(tmp_path / "missing.json"), "--base", str(path),
                       "--nondet-lines", str(empty),
                       "--output", str(tmp_path / "out.json")]) == 1
    assert not (tmp_path / "out.json").exists()


def test_real_count_aggregation_checks_total_and_paths(tmp_path):
    path = tmp_path / "coverage.json"
    data = {"files": {"src/backend/app/domain/a.py": {"summary": {
        "covered_lines": 5, "num_statements": 10}}},
        "totals": {"covered_lines": 5, "num_statements": 10}}
    path.write_text(json.dumps(data))
    counts = ratchet.measured(path)
    assert counts["total"] == counts["domain"] == [5, 10]
    data["totals"]["covered_lines"] = 6
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        ratchet.measured(path)


def test_event_base_is_main_not_pr_head():
    base = "b" * 40
    event = {"pull_request": {"base": {"sha": base, "ref": "main",
             "repo": {"full_name": "owner/repo"}}, "head": {"sha": "a" * 40}}}
    assert loader.base_identity(event, {"GITHUB_REPOSITORY": "owner/repo",
                                       "GITHUB_EVENT_NAME": "pull_request"}) == ("owner/repo", base)
    event["pull_request"]["base"]["repo"]["full_name"] = "foreign/repo"
    with pytest.raises(ValueError):
        loader.base_identity(event, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "pull_request"})


def test_merge_group_base_is_main_not_queue_head():
    base = "b" * 40
    event = {"merge_group": {"base_ref": "refs/heads/main", "base_sha": base,
                             "head_sha": "a" * 40}}
    env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "merge_group",
           "GITHUB_REF": "refs/heads/gh-readonly-queue/main/pr-7-synthetic"}
    assert loader.base_identity(event, env) == ("owner/repo", base)


@pytest.mark.parametrize("base_ref", ["refs/heads/develop", "main", "refs/tags/main", ""])
def test_merge_group_rejects_non_main_base(base_ref):
    with pytest.raises(ValueError, match="trusted main"):
        loader.base_identity({"merge_group": {"base_ref": base_ref, "base_sha": "b" * 40}},
                             {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "merge_group"})


@pytest.mark.parametrize("fields", [{}, {"base_sha": "0" * 40}, {"base_sha": ""},
                                   {"base_sha": "b" * 39}, {"base_sha": "g" * 40}])
def test_merge_group_rejects_missing_or_invalid_base_sha(fields):
    with pytest.raises(ValueError, match="Missing trusted base commit"):
        loader.base_identity({"merge_group": {"base_ref": "refs/heads/main", **fields}},
                             {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "merge_group"})


def archive(record):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as stream:
        stream.writestr("coverage-ratchet-measurement.json", json.dumps(record))
    return buffer.getvalue()


@pytest.mark.parametrize("change", ["commit", "run_id", "attempt", "ratchet_passed", "selection"])
def test_base_artifact_rejects_wrong_identity_or_selection(change):
    record = deepcopy(ratchet.bootstrap_record())
    record.update(commit="b" * 40, run_id="123", attempt="1")
    record[change] = False if change == "ratchet_passed" else "wrong"
    with pytest.raises(ValueError):
        loader.read_artifact(archive(record), "b" * 40, 123, 1)


def test_only_reviewed_first_base_can_bootstrap(monkeypatch):
    monkeypatch.setattr(loader.subprocess, "run", Mock(side_effect=[
        SimpleNamespace(returncode=0), SimpleNamespace(returncode=128)]))
    get = Mock()
    record = loader.freeze("owner/repo", ratchet.BOOTSTRAP_BASE, get)
    assert record["counts"]["total"] == [15571, 22926]
    get.assert_not_called()
    monkeypatch.setattr(loader.subprocess, "run", Mock(side_effect=[
        SimpleNamespace(returncode=0), SimpleNamespace(returncode=128)]))
    with pytest.raises(ValueError):
        loader.freeze("owner/repo", "c" * 40, get)


def test_later_base_requires_its_push_artifact_never_resets(monkeypatch):
    monkeypatch.setattr(loader.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    sha = "b" * 40
    record = deepcopy(ratchet.bootstrap_record())
    record.update(commit=sha, run_id="123", attempt="2")
    record["counts"]["total"][0] += 1
    get = Mock(side_effect=[{"workflow_runs": [{"id": 123, "run_attempt": 2,
        "head_sha": sha, "head_branch": "main", "event": "push", "status": "completed",
        "repository": {"full_name": "owner/repo"}}]},
        {"artifacts": [{"id": 456, "name": "coverage-ratchet-123-2", "expired": False}]},
        archive(record)])
    frozen = loader.freeze("owner/repo", sha, get)
    assert frozen["counts"]["total"][0] == 15572
    get = Mock(return_value={"workflow_runs": []})
    with pytest.raises(ValueError):
        loader.freeze("owner/repo", sha, get)


@pytest.mark.parametrize("expired", [True, False])
def test_expired_or_missing_base_artifact_cannot_fall_back(monkeypatch, expired):
    monkeypatch.setattr(loader.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    sha = "b" * 40
    artifacts = ([{"id": 456, "name": "coverage-ratchet-123-1", "expired": True}]
                 if expired else [])
    get = Mock(side_effect=[{"workflow_runs": [{"id": 123, "run_attempt": 1,
        "head_sha": sha, "head_branch": "main", "event": "push", "status": "completed",
        "repository": {"full_name": "owner/repo"}}]}, {"artifacts": artifacts}])
    with pytest.raises(ValueError):
        loader.freeze("owner/repo", sha, get)
    assert get.call_count == 2


def test_download_redirect_removes_token_across_hosts():
    import urllib.request

    request = urllib.request.Request("https://api.github.com/example", headers={
        "Authorization": "Bearer synthetic-test-only"})
    redirected = loader.SafeRedirect().redirect_request(request, None, 302, "found", {},
                                                        "https://example.invalid/archive.zip")
    assert not redirected.has_header("Authorization")


def test_workflow_keeps_full_selection_and_only_changes_coverage_gate():
    workflow = (Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "for d in src/backend/tests tests/backend tests/replay; do" in workflow
    assert "--cov=src/backend/app --cov-report=term-missing:skip-covered" in workflow
    assert "--cov-fail-under=80" not in workflow
    assert "timeout-minutes: 30" in workflow
    assert "!cancelled() && steps.coverage_ratchet.outcome != 'skipped'" in workflow
    assert "steps.coverage_ratchet.outcome == 'success'" not in workflow
    assert '--base-coverage "${RUNNER_TEMP}/coverage-base-coverage.json"' in workflow
    assert "--nondet-lines scripts/ci/coverage-nondet-lines.json" in workflow
    assert "fetch-depth: 0" in workflow and "GH_TOKEN: ${{ github.token }}" in workflow


def test_pending_exact_main_push_is_distinct_from_missing_measurement(monkeypatch):
    monkeypatch.setattr(loader.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    sha = "b" * 40
    get = Mock(side_effect=[{"workflow_runs": []}, {"workflow_runs": [{
        "id": 123, "head_sha": sha, "head_branch": "main", "event": "push",
        "status": "in_progress", "repository": {"full_name": "owner/repo"}}]}])
    with pytest.raises(loader.MeasurementPending) as caught:
        loader.freeze("owner/repo", sha, get)
    assert caught.value.sha == sha and caught.value.run_id == 123
    assert get.call_count == 2


@pytest.mark.parametrize("change", ["head_sha", "head_branch", "event", "repository", "status"])
def test_foreign_pr_or_finished_run_cannot_authorize_wait(monkeypatch, change):
    monkeypatch.setattr(loader.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    sha = "b" * 40
    run = {"id": 123, "head_sha": sha, "head_branch": "main", "event": "push",
           "status": "in_progress", "repository": {"full_name": "owner/repo"}}
    run[change] = {"full_name": "foreign/repo"} if change == "repository" else "wrong"
    get = Mock(side_effect=[{"workflow_runs": []}, {"workflow_runs": [run]}])
    with pytest.raises(ValueError, match="No completed exact-base"):
        loader.freeze("owner/repo", sha, get)


def test_wait_uses_original_main_run_then_validated_measurement(monkeypatch):
    record = ratchet.bootstrap_record()
    freeze = Mock(side_effect=loader.MeasurementPending("b" * 40, 123))
    monkeypatch.setattr(loader, "freeze", freeze)
    exact = Mock(return_value=record)
    monkeypatch.setattr(loader, "_freeze_exact", exact)
    monkeypatch.setattr(loader.time, "monotonic", Mock(side_effect=[0, 0]))
    sleep = Mock()
    monkeypatch.setattr(loader.time, "sleep", sleep)
    get = Mock()
    assert loader.wait_for_base("owner/repo", "b" * 40, get, 30) is record
    assert freeze.call_count == 1
    exact.assert_called_once_with("owner/repo", "b" * 40, get,
                                  unavailable=ValueError, known_run_id=123)
    sleep.assert_called_once_with(15)


def test_wait_timeout_and_invalid_artifact_fail_without_fallback(monkeypatch):
    freeze = Mock(side_effect=loader.MeasurementPending("b" * 40, 123))
    monkeypatch.setattr(loader, "freeze", freeze)
    monkeypatch.setattr(loader.time, "monotonic", Mock(side_effect=[0, 30]))
    sleep = Mock()
    monkeypatch.setattr(loader.time, "sleep", sleep)
    with pytest.raises(loader.MeasurementPending):
        loader.wait_for_base("owner/repo", "b" * 40, Mock(), 30)
    assert freeze.call_count == 1
    sleep.assert_not_called()
    freeze.side_effect = ValueError("Missing, expired or ambiguous exact-base measurement")
    monkeypatch.setattr(loader.time, "monotonic", Mock(return_value=0))
    with pytest.raises(ValueError, match="Missing, expired"):
        loader.wait_for_base("owner/repo", "b" * 40, Mock(), 30)
    sleep.assert_not_called()


def test_backend_runs_in_parallel_then_freezes_base_before_ratchet():
    import yaml

    path = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml"
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    ready = jobs["coverage-base"]
    backend = jobs["backend"]
    # Classification runs first on PRs; all other events retain full CI, including merge_group.
    expected_if = "${{ github.event_name != 'pull_request' || needs.changes.outputs.docs_only != 'true' }}"
    assert ready["needs"] == "changes"
    assert ready["if"] == expected_if
    for upstream in ("backend-lint", "backend-mypy", "backend-tests"):
        assert jobs[upstream]["needs"] == "changes"
        assert jobs[upstream]["if"] == expected_if
    assert backend["needs"] == ["changes", "backend-lint", "backend-mypy", "backend-tests"]
    assert backend["if"] == "${{ always() && (github.event_name != 'pull_request' || needs.changes.outputs.docs_only != 'true') }}"
    # T-O89：保留 T-O80 的 45 分钟运行预算，另加最多 30 分钟基线等待。
    assert backend["timeout-minutes"] == 75
    assert backend["name"] == "backend (ruff, mypy, pytest+coverage)"
    shards = jobs["backend-tests"]
    assert shards["strategy"] == {"fail-fast": False, "matrix": {"shard": [1, 2, 3, 4, 5, 6]}}
    assert shards["timeout-minutes"] == 30
    assert shards["name"] == "backend tests (shard ${{ matrix.shard }}/6)"
    # Job-level env reaches every matrix shard, including src/backend/tests real-PG cases.
    assert shards["env"]["AIA_TEST_DATABASE_URL"] == "postgresql://aia:ci-only@127.0.0.1:5432/aia"
    assert shards["services"]["db"]["ports"] == ["5432:5432"]
    assert jobs["backend-lint"]["name"] == "backend lint (ruff)"
    assert jobs["backend-mypy"]["name"] == "backend typecheck (mypy --strict)"
    assert ready["name"] == "trusted main coverage readiness"
    assert ready["timeout-minutes"] == 35
    assert ready["permissions"] == {"contents": "read", "actions": "read"}
    commands = [step["run"] for step in ready["steps"] if "run" in step]
    assert len(commands) == 1 and "--wait-for-main-seconds 1800" in commands[0]
    assert "pytest" not in commands[0] and "rerun" not in commands[0]
    steps = backend["steps"]
    freezes = [i for i, step in enumerate(steps)
               if "scripts/ci/coverage_ratchet_base.py" in step.get("run", "")]
    assert len(freezes) == 1
    freeze_index = freezes[0]
    merge_index = next(i for i, step in enumerate(steps) if "coverage combine" in step.get("run", ""))
    merge = steps[merge_index]
    assert "set -euo pipefail" in merge["run"]
    assert merge["run"].index('"$py" scripts/ci/check_coverage_data.py') < merge["run"].index('"$py" -m coverage combine')
    assert 'scripts/ci/check_coverage_data.py "${RUNNER_TEMP}"/shards/*/coverage-shard-*.data' in merge["run"]
    assert not merge.get("continue-on-error", False)
    union_index = next(i for i, step in enumerate(steps) if "scripts/ci/check_shard_union.py" in step.get("run", ""))
    assert union_index < merge_index
    assert '--junit "${RUNNER_TEMP}/shards"' in steps[union_index]["run"]
    assert "scripts/ci/merge_junit.py" in merge["run"]
    ratchet_index = next(i for i, step in enumerate(steps) if step.get("id") == "coverage_ratchet")
    assert merge_index < freeze_index == ratchet_index - 1
    frozen = steps[freeze_index]
    assert frozen["run"] == ('python3 scripts/ci/coverage_ratchet_base.py '
                             '--wait-for-main-seconds 1800 --output "${RUNNER_TEMP}/coverage-base.json" '
                             '--coverage-output "${RUNNER_TEMP}/coverage-base-coverage.json"')
    assert frozen["if"] == steps[ratchet_index]["if"]
    assert frozen["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert not frozen.get("continue-on-error", False)


@pytest.mark.parametrize("exit_code,with_ini", [(0, True), (1, True), (5, False)])
def test_backend_pytest_adds_durations_preserving_argv_and_exit(tmp_path, monkeypatch, exit_code, with_ini):
    import yaml

    path = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml"
    backend = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["backend-tests"]
    command = next(step["run"] for step in backend["steps"] if step.get("name") == "pytest + 覆盖率")
    dirs = ["src/backend/tests", "tests/backend", "tests/replay"]
    for directory in dirs + ["src/backend/.venv/bin", "bin", "runner temp"]:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    if with_ini:
        (tmp_path / "tests/pytest.ini").touch()
    runner_temp = tmp_path / "runner temp"
    python = tmp_path / "src/backend/.venv/bin/python"
    python.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1:] == ['scripts/ci/observe_template_connections.py']:\n"
        "    sys.exit(23)  # Observer failure must not replace pytest's exit.\n"
        "assert os.environ['PYTHONPATH'] == 'src/backend'\n"
        "assert os.environ['AIA_SHARD_REPORT'] == str(Path(os.environ['RUNNER_TEMP'], 'shard-report.json'))\n"
        "assert os.environ['COVERAGE_FILE'] == str(Path(os.environ['RUNNER_TEMP'], 'coverage-shard-3.data'))\n"
        "Path(os.environ['RUNNER_TEMP'], 'argv.json').write_text(json.dumps(sys.argv[1:]))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    uv = tmp_path / "bin/uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(uv.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("AIA_SHARD_INDEX", "3")
    monkeypatch.setenv("AIA_SHARD_TOTAL", "6")
    for name in ("PYTEST_COV_VERSION", "REQUESTS_VERSION", "URLLIB3_VERSION"):
        monkeypatch.setenv(name, "test-only")
    result = subprocess.run(["bash", "-c", command], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert json.loads((runner_temp / "argv.json").read_text(encoding="utf-8")) == [
        "-m", "pytest", "-p", "scripts.ci.pytest_safe_failures",
        "-p", "scripts.ci.pytest_shard",
        *(["-c", "tests/pytest.ini"] if with_ini else []), *dirs,
        "--durations=30", "--durations-min=0.5",
        "--cov=src/backend/app", "--cov-report=term-missing:skip-covered",
        f"--junitxml={runner_temp}/backend-pytest-shard-3.xml",
    ]


class SettleClock:
    """All readiness polls advance virtual time, never wall time."""

    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 15
        self.sleeps.append(seconds)
        self.now += seconds


class SettlingActions:
    """Completed-list indexing lags the active list and direct run endpoint."""

    sha = "b" * 40
    repo = "owner/repo"

    def __init__(self, clock, *, empty_lists=0, mode="valid", completed_after=15):
        self.clock = clock
        self.empty_lists = empty_lists
        self.mode = mode
        self.completed_after = completed_after
        self.artifact_lists = 0
        self.calls = []
        self.overrides = {}
        self.http_endpoint = None
        self.http_code = 404
        self.http_failures = 0

    def run(self):
        return {"id": 123, "run_attempt": 1, "head_sha": self.sha,
                "head_branch": "main", "event": "push",
                "status": "completed" if self.clock.now >= self.completed_after else "in_progress",
                "repository": {"full_name": self.repo}, "path": ".github/workflows/ci.yml"}

    def __call__(self, path, *, binary=False):
        self.calls.append((self.clock.now, path))
        if self.http_endpoint and self.http_endpoint in path and self.http_failures:
            self.http_failures -= 1
            # Synthetic hostile error text must never reach the error annotation.
            raise urllib.error.HTTPError("https://example.invalid/?token=synthetic-private",
                                         self.http_code, "synthetic-private", {}, None)
        if "/ci.yml/runs?" in path:
            return {"workflow_runs": [] if "status=completed" in path else [self.run()]}
        if path == "/actions/runs/123":
            return self.run() | self.overrides
        if path == "/actions/runs/123/artifacts?per_page=100":
            self.artifact_lists += 1
            artifacts = [] if self.artifact_lists <= self.empty_lists else [
                {"id": 456, "name": "coverage-ratchet-123-1", "expired": self.mode == "expired"}]
            if self.mode == "ambiguous":
                artifacts *= 2
            return {"artifacts": artifacts}
        assert path == "/actions/artifacts/456/zip" and binary
        if self.mode == "bad_zip":
            return b"synthetic invalid archive"
        record = deepcopy(ratchet.bootstrap_record())
        record.update(commit=self.sha, run_id="123", attempt="1")
        if self.mode == "failed_ratchet":
            record["ratchet_passed"] = False
        elif self.mode == "wrong_identity":
            record["commit"] = "c" * 40
        return archive(record)


@pytest.fixture
def settle_clock(monkeypatch):
    clock = SettleClock()
    monkeypatch.setattr(loader.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(loader.time, "sleep", clock.sleep)
    monkeypatch.setattr(loader.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    return clock


def test_settle_completed_index_race_uses_observed_pending_run(settle_clock):
    actions = SettlingActions(settle_clock)
    record = loader.wait_for_base(actions.repo, actions.sha, actions, 1800)
    assert record["source"]["run_id"] == 123
    assert record["source"]["commit"] == actions.sha
    assert settle_clock.sleeps == [15]
    assert actions.calls[:3] == [
        (0, "/actions/workflows/ci.yml/runs?event=push&branch=main&status=completed&head_sha="
         + actions.sha + "&per_page=100"),
        (0, "/actions/workflows/ci.yml/runs?event=push&branch=main&head_sha="
         + actions.sha + "&per_page=100"),
        (15, "/actions/runs/123"),
    ]
    # At poll 2 the filtered list is still empty, while the active list is
    # completed. Direct lookup bypasses both eventually consistent indexes.
    assert not actions("/actions/workflows/ci.yml/runs?status=completed")["workflow_runs"]
    assert actions("/actions/workflows/ci.yml/runs?event=push")["workflow_runs"][0]["status"] == "completed"


@pytest.mark.parametrize("allow_fallback", [False, True])
def test_settle_artifact_third_listing_succeeds_past_pending_deadline(settle_clock, allow_fallback):
    actions = SettlingActions(settle_clock, empty_lists=2)
    record = loader.wait_for_base(actions.repo, actions.sha, actions, 15, allow_fallback=allow_fallback)
    assert record["source"]["run_id"] == 123
    assert "fallback" not in record["source"]
    assert actions.artifact_lists == 3
    assert settle_clock.now == 45  # Original pending deadline was 15 s.


def test_settle_missing_artifact_fails_at_fixed_grace_limit(settle_clock):
    actions = SettlingActions(settle_clock, empty_lists=999)
    with pytest.raises(ValueError, match="Missing, expired or ambiguous") as caught:
        loader.wait_for_base(actions.repo, actions.sha, actions, 1800)
    assert type(caught.value) is ValueError  # Preserve the original unavailable category.
    assert loader.SETTLE_SECONDS == 120
    assert 15 + loader.SETTLE_SECONDS <= settle_clock.now <= 15 + loader.SETTLE_SECONDS + 15
    assert actions.artifact_lists == 9


def test_settle_total_wait_is_capped_below_readiness_timeout(settle_clock):
    actions = SettlingActions(settle_clock, empty_lists=999, completed_after=1800)
    with pytest.raises(ValueError, match="Missing, expired or ambiguous"):
        loader.wait_for_base(actions.repo, actions.sha, actions, 1800)
    assert loader.MAX_WAIT_SECONDS == 1920 < 35 * 60
    assert settle_clock.now == loader.MAX_WAIT_SECONDS


@pytest.mark.parametrize("mode,exception", [
    ("failed_ratchet", ValueError), ("wrong_identity", ValueError),
    ("bad_zip", zipfile.BadZipFile), ("expired", ValueError), ("ambiguous", ValueError),
])
@pytest.mark.parametrize("empty_lists", [0, 2])
def test_settle_invalid_artifact_fails_immediately(settle_clock, mode, exception, empty_lists):
    actions = SettlingActions(settle_clock, mode=mode, empty_lists=empty_lists)
    with pytest.raises(exception):
        loader.wait_for_base(actions.repo, actions.sha, actions, 1800)
    assert settle_clock.now == 15 * (1 + empty_lists)
    assert actions.artifact_lists == 1 + empty_lists
    assert settle_clock.sleeps == [15] * (1 + empty_lists)  # No retry after invalid data.


def test_settle_never_pending_missing_run_fails_immediately(settle_clock):
    get = Mock(return_value={"workflow_runs": []})
    with pytest.raises(ValueError, match="No completed exact-base"):
        loader.wait_for_base("owner/repo", "b" * 40, get, 1800)
    assert get.call_count == 2
    assert settle_clock.now == 0 and not settle_clock.sleeps


@pytest.mark.parametrize("change,value", [
    ("head_sha", "c" * 40), ("head_branch", "topic"), ("event", "pull_request"),
    ("repository", {"full_name": "foreign/repo"}),
    ("path", ".github/workflows/untrusted.yml"), ("path", None), ("id", 456),
])
def test_settle_direct_run_requires_all_trusted_identity_fields(settle_clock, change, value):
    actions = SettlingActions(settle_clock)
    actions.overrides[change] = value
    with pytest.raises(ValueError, match="Known main measurement run identity mismatch"):
        loader.wait_for_base(actions.repo, actions.sha, actions, 1800)
    assert actions.artifact_lists == 0 and settle_clock.now == 15


@pytest.mark.parametrize("endpoint", ["/artifacts?", "/zip"])
def test_settle_artifact_http_404_is_retried(settle_clock, endpoint):
    actions = SettlingActions(settle_clock)
    actions.http_endpoint, actions.http_failures = endpoint, 2
    assert loader.wait_for_base(actions.repo, actions.sha, actions, 1800)["source"]["run_id"] == 123
    assert settle_clock.now == 45


def test_settle_direct_run_404_is_not_artifact_latency(settle_clock):
    actions = SettlingActions(settle_clock)
    actions.http_endpoint, actions.http_failures = "/actions/runs/123", 1
    with pytest.raises(urllib.error.HTTPError) as caught:
        loader.wait_for_base(actions.repo, actions.sha, actions, 1800, allow_fallback=True)
    assert caught.value.code == 404
    assert settle_clock.now == 15 and actions.artifact_lists == 0


@pytest.mark.parametrize("endpoint", ["/actions/runs/123", "/artifacts?", "/zip"])
@pytest.mark.parametrize("code", [401, 403, 429, 500, 503])
def test_settle_other_http_errors_fail_without_retry(settle_clock, endpoint, code):
    actions = SettlingActions(settle_clock)
    actions.http_endpoint, actions.http_failures, actions.http_code = endpoint, 1, code
    with pytest.raises(urllib.error.HTTPError) as caught:
        loader.wait_for_base(actions.repo, actions.sha, actions, 1800, allow_fallback=True)
    assert caught.value.code == code
    assert settle_clock.now == 15


def test_settle_network_error_is_not_retried(settle_clock):
    actions = SettlingActions(settle_clock)

    def get(path, **kwargs):
        if path == "/actions/runs/123":
            raise urllib.error.URLError("synthetic-private")
        return actions(path, **kwargs)

    with pytest.raises(urllib.error.URLError):
        loader.wait_for_base(actions.repo, actions.sha, get, 1800, allow_fallback=True)
    assert settle_clock.now == 15


@pytest.mark.parametrize("allow_fallback", [False, True])
def test_settle_pending_timeout_never_enters_fallback(settle_clock, capsys, allow_fallback):
    actions = SettlingActions(settle_clock, completed_after=9999)
    with pytest.raises(loader.MeasurementPending, match="timed out after 30 s waiting for run 123"):
        loader.wait_for_base(actions.repo, actions.sha, actions, 30, allow_fallback=allow_fallback)
    assert settle_clock.now == 30
    assert actions.artifact_lists == 0
    assert "Waiting for existing trusted main run 123" in capsys.readouterr().out


@pytest.mark.parametrize("mode,empty_lists,expected_time", [
    ("valid", 999, 135), ("failed_ratchet", 0, 15), ("bad_zip", 0, 15),
])
def test_settle_releases_to_existing_fallback_only_after_unavailable(
        monkeypatch, settle_clock, mode, empty_lists, expected_time):
    actions = SettlingActions(settle_clock, mode=mode, empty_lists=empty_lists)
    # Model freeze's existing ancestor policy without implementing/changing it.
    recovered = {"source": {"kind": "existing-fallback"}}
    freeze = Mock(side_effect=[loader.MeasurementPending(actions.sha, 123), recovered])
    monkeypatch.setattr(loader, "freeze", freeze)
    assert loader.wait_for_base(actions.repo, actions.sha, actions, 1800, allow_fallback=True) is recovered
    assert freeze.call_count == 2
    assert settle_clock.now == expected_time
    assert all(call.kwargs == {"allow_fallback": True} for call in freeze.call_args_list)


def setup_settle_cli(monkeypatch, tmp_path, actions, timeout=30):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"pull_request": {"base": {
        "sha": actions.sha, "ref": "main", "repo": {"full_name": actions.repo}}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", actions.repo)
    monkeypatch.setenv("GH_TOKEN", "synthetic-private")
    monkeypatch.setattr(loader, "api_reader", Mock(return_value=actions))
    monkeypatch.setattr(sys, "argv", ["coverage_ratchet_base.py", "--output", str(tmp_path / "out.json"),
                                     "--wait-for-main-seconds", str(timeout)])


def test_settle_cli_pending_timeout_includes_run_and_duration(monkeypatch, tmp_path, settle_clock, capsys):
    actions = SettlingActions(settle_clock, completed_after=9999)
    setup_settle_cli(monkeypatch, tmp_path, actions)
    assert loader.main() == 1
    assert "MeasurementPending: timed out after 30 s waiting for run 123" in capsys.readouterr().out
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("kind,reason", [
    ("missing", "MeasurementUnavailable: No usable trusted main push measurement within 0 first-parent ancestors"),
    ("invalid", "MeasurementUnavailable: No usable trusted main push measurement within 0 first-parent ancestors"),
    ("ratchet", "ValueError: Artifact ratchet_passed is not true"),
    ("http", "HTTPError: HTTP status 403"),
    ("network", "URLError: Could not read or validate trusted base measurement data"),
    ("external_value", "ValueError: Could not read or validate trusted base measurement data"),
    ("key", "KeyError: Could not read or validate trusted base measurement data"),
])
def test_settle_cli_error_reason_never_echoes_token(monkeypatch, tmp_path, settle_clock, capsys, kind, reason):
    actions = SettlingActions(settle_clock, mode="failed_ratchet" if kind == "invalid" else "valid")
    setup_settle_cli(monkeypatch, tmp_path, actions)
    if kind in {"missing", "invalid"}:
        # Bound recovery explicitly: these error cases have no usable ancestor.
        # The fake git runner supplies policy existence, not a real history.
        monkeypatch.setattr(loader, "MAX_FALLBACK_ANCESTORS", 0)
    if kind == "missing":
        monkeypatch.setattr(loader, "api_reader", Mock(return_value=Mock(return_value={"workflow_runs": []})))
    elif kind == "ratchet":
        monkeypatch.setattr(loader, "api_reader", Mock(return_value=Mock(
            side_effect=ValueError("Artifact ratchet_passed is not true"))))
    elif kind == "http":
        actions.http_endpoint, actions.http_failures, actions.http_code = "/actions/runs/123", 1, 403
    elif kind in {"network", "external_value", "key"}:
        error = {"network": urllib.error.URLError, "external_value": ValueError, "key": KeyError}[kind]
        monkeypatch.setattr(loader, "api_reader", Mock(return_value=Mock(side_effect=error(
            "synthetic-private Authorization: Bearer synthetic-private https://example.invalid/private"))))
    assert loader.main() == 1
    output = capsys.readouterr().out
    error_line = next(line for line in output.splitlines() if line.startswith("::error"))
    assert "Trusted base measurement unavailable or invalid; " + reason in error_line
    assert "synthetic-private" not in output
    assert "https://" not in error_line and "Authorization" not in error_line
