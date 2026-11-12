"""Coverage policy counterexamples use synthetic counts, no services or network."""
import io
import json
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
    assert check.main([str(tmp_path / "missing.json"), "--base", str(path),
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
    assert "steps.coverage_ratchet.outcome == 'success'" in workflow
    assert "fetch-depth: 0" in workflow and "GH_TOKEN: ${{ github.token }}" in workflow
