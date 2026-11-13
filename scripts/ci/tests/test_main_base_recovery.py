"""User-A recovery uses disposable Git history and synthetic Actions artifacts only."""
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import zipfile
from copy import deepcopy

import coverage_ratchet as ratchet
import coverage_ratchet_base as loader
import pytest

REPO = "owner/repo"


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "user.name=Synthetic CI", "-c", "user.email=ci@example.invalid",
         "-C", str(root), *args], text=True, encoding="utf-8").strip()


def commit(root, label):
    git(root, "commit", "--allow-empty", "-qm", label)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-main"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    policy = root / loader.POLICY_PATH
    policy.parent.mkdir(parents=True)
    policy.write_text("{}\n", encoding="utf-8")
    git(root, "add", loader.POLICY_PATH)
    first = commit(root, "root with policy")
    second = commit(root, "unmeasured main")
    third = commit(root, "recovery main")
    monkeypatch.setattr(loader, "ROOT", root)
    return root, (first, second, third)


@pytest.fixture(autouse=True)
def reject_real_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline recovery tests must not open HTTP connections")
    monkeypatch.setattr(loader.urllib.request.OpenerDirector, "open", denied)


class Actions:
    def __init__(self):
        self.states = {}
        self.calls = []

    def put(self, sha, mode="valid"):
        identifier = 100 + len(self.states)
        self.states[sha] = (identifier, mode)

    def __call__(self, path, *, binary=False):
        self.calls.append(path)
        parsed = urllib.parse.urlsplit(path)
        if parsed.path.endswith("/ci.yml/runs"):
            query = urllib.parse.parse_qs(parsed.query)
            sha = query["head_sha"][0]
            if sha not in self.states:
                return {"workflow_runs": []}
            identifier, mode = self.states[sha]
            status = "in_progress" if mode == "pending" else "completed"
            if query.get("status") == ["completed"] and status != "completed":
                return {"workflow_runs": []}
            event = mode if mode in {"pull_request", "workflow_dispatch"} else "push"
            return {"workflow_runs": [{
                "id": identifier, "run_attempt": 1, "head_sha": sha,
                "head_branch": "main", "event": event, "status": status,
                "repository": {"full_name": "foreign/repo" if mode == "foreign" else REPO},
            }]}
        identifier = int(parsed.path.split("/")[-2])
        sha, (_, mode) = next((sha, value) for sha, value in self.states.items()
                              if value[0] == identifier)
        if parsed.path.endswith("/artifacts"):
            artifacts = [] if mode == "no_artifact" else [{
                "id": identifier, "name": f"coverage-ratchet-{identifier}-1",
                "expired": mode == "expired",
            }]
            if mode == "ambiguous":
                artifacts *= 2
            return {"artifacts": artifacts}
        assert parsed.path == f"/actions/artifacts/{identifier}/zip" and binary
        if mode == "invalid_zip":
            return b"synthetic invalid archive"
        record = deepcopy(ratchet.bootstrap_record())
        record.update(commit=sha, run_id=str(identifier), attempt="1")
        if mode == "failed_ratchet":
            record["ratchet_passed"] = False
        elif mode == "wrong_identity":
            record["commit"] = "f" * 40
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("coverage-ratchet-measurement.json", json.dumps(record))
        return archive.getvalue()


def assert_fallback(record, selected, requested, skipped):
    assert record["commit"] == selected
    assert record["ratchet_passed"] is True
    assert record["source"]["kind"] == "trusted-main-push-artifact"
    assert record["source"]["commit"] == selected
    assert record["source"]["fallback"] == {
        "requested_base_commit": requested, "skipped_heads": skipped,
        "ancestor_limit": loader.MAX_FALLBACK_ANCESTORS,
    }


def test_missing_exact_base_recovers_nearest_measured_first_parent(history):
    assert loader.MAX_FALLBACK_ANCESTORS == 50
    _, (first, second, third) = history
    actions = Actions()
    actions.put(first)
    actions.put(second)
    record = loader.freeze(REPO, third, actions, allow_fallback=True)
    assert_fallback(record, second, third, 1)
    assert not any(first in call for call in actions.calls)


@pytest.mark.parametrize("mode", [
    "no_artifact", "expired", "ambiguous", "failed_ratchet", "wrong_identity", "invalid_zip",
    "pull_request", "workflow_dispatch", "foreign",
])
def test_unusable_or_untrusted_head_never_becomes_recovered_baseline(history, mode):
    _, (_, second, third) = history
    actions = Actions()
    actions.put(second)
    actions.put(third, mode)
    record = loader.freeze(REPO, third, actions, allow_fallback=True)
    assert_fallback(record, second, third, 1)


def test_all_missing_history_still_errors_instead_of_bootstrap_reset(history):
    _, heads = history
    actions = Actions()
    with pytest.raises(ValueError, match="No usable trusted main push measurement"):
        loader.freeze(REPO, heads[-1], actions, allow_fallback=True)
    for head in heads:
        assert any(head in call for call in actions.calls)


@pytest.mark.parametrize("distance,success", [(2, True), (3, False)])
def test_ancestor_bound_includes_boundary_but_never_queries_beyond_it(
    history, monkeypatch, distance, success,
):
    root, (first, _, third) = history
    requested = third if distance == 2 else commit(root, "one beyond the bound")
    monkeypatch.setattr(loader, "MAX_FALLBACK_ANCESTORS", 2)
    actions = Actions()
    actions.put(first)
    if success:
        assert_fallback(loader.freeze(REPO, requested, actions, allow_fallback=True),
                        first, requested, 2)
    else:
        with pytest.raises(ValueError, match="No usable trusted main push measurement"):
            loader.freeze(REPO, requested, actions, allow_fallback=True)
        assert not any(first in call for call in actions.calls)


def test_recovery_never_takes_a_merge_second_parent_measurement(history):
    root, (first, _, third) = history
    git(root, "checkout", "-qb", "side", first)
    side = commit(root, "side-only measurement")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "--no-ff", "-qm", "main merge", "side")
    merged = git(root, "rev-parse", "HEAD")
    assert git(root, "rev-parse", merged + "^1") == third
    assert git(root, "rev-parse", merged + "^2") == side
    actions = Actions()
    actions.put(first)
    actions.put(side)
    record = loader.freeze(REPO, merged, actions, allow_fallback=True)
    assert_fallback(record, first, merged, 3)
    assert not any(side in call for call in actions.calls)


def test_exact_valid_base_keeps_existing_source_without_fallback(history):
    _, (_, _, third) = history
    actions = Actions()
    actions.put(third)
    record = loader.freeze(REPO, third, actions, allow_fallback=True)
    assert record["source"] == {
        "kind": "trusted-main-push-artifact", "commit": third,
        "run_id": 100, "attempt": 1,
    }


def test_existing_pending_exact_run_still_waits_without_ancestor_requests(history):
    _, (_, second, third) = history
    actions = Actions()
    actions.put(second)
    actions.put(third, "pending")
    with pytest.raises(loader.MeasurementPending):
        loader.freeze(REPO, third, actions, allow_fallback=True)
    assert not any(second in call for call in actions.calls)


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("https://example.invalid", 403, "synthetic denied", {}, None),
    urllib.error.URLError("synthetic transport failure"),
])
def test_authentication_or_transport_failure_is_not_hidden_by_ancestry(history, error):
    _, (_, _, third) = history
    calls = []
    def denied(path, **kwargs):
        calls.append(path)
        raise error
    with pytest.raises(type(error)):
        loader.freeze(REPO, third, denied, allow_fallback=True)
    assert len(calls) == 1


@pytest.mark.parametrize("event_name", ["push", "workflow_dispatch", "pull_request"])
def test_cli_allows_main_events_to_recover_but_pr_remains_exact(
    history, tmp_path, monkeypatch, capsys, event_name,
):
    _, (first, _, third) = history
    actions = Actions()
    actions.put(first)
    event = {"before": third, "pull_request": {
        "base": {"sha": third, "ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": "a" * 40},
    }}
    path = tmp_path / "synthetic-event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    output = tmp_path / "frozen.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/pull/7/merge" if event_name == "pull_request"
                       else "refs/heads/main")
    monkeypatch.setattr(loader, "api_reader", lambda repo: actions)
    monkeypatch.setattr(sys, "argv", ["loader", "--output", str(output)])
    result = loader.main()
    if event_name == "pull_request":
        assert result == 1 and not output.exists()
        assert all(third in call for call in actions.calls)
    else:
        assert result == 0
        frozen = json.loads(output.read_text(encoding="utf-8"))
        assert frozen["commit"] == first
        assert "Frozen coverage baseline: " + first in capsys.readouterr().out


def test_tag_dispatch_context_is_still_rejected_before_any_measurement():
    with pytest.raises(ValueError, match="Unsupported coverage baseline context"):
        loader.base_identity({}, {
            "GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/tags/synthetic-recovery",
        })


def test_bootstrap_exact_head_is_unchanged_even_when_recovery_is_enabled(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.setattr(loader.subprocess, "run", Mock(side_effect=[
        SimpleNamespace(returncode=0), SimpleNamespace(returncode=128),
    ]))
    actions = Mock()
    record = loader.freeze(REPO, ratchet.BOOTSTRAP_BASE, actions, allow_fallback=True)
    assert record["source"]["kind"] == "approved-first-bootstrap"
    assert record["counts"]["total"] == [15571, 22926]
    actions.assert_not_called()


def test_no_new_fallback_can_reset_to_an_unmeasured_bootstrap_ancestor(history, monkeypatch):
    root, (first, _, third) = history
    monkeypatch.setattr(loader, "BOOTSTRAP_BASE", first)
    original = loader.subprocess.run
    def policy_absent_at_seed(argv, **kwargs):
        if argv[:3] == ["git", "show", first + ":" + loader.POLICY_PATH]:
            from types import SimpleNamespace
            return SimpleNamespace(returncode=128)
        return original(argv, **kwargs)
    monkeypatch.setattr(loader.subprocess, "run", policy_absent_at_seed)
    with pytest.raises(ValueError, match="No usable trusted main push measurement"):
        loader.freeze(REPO, third, Actions(), allow_fallback=True)
    assert root.exists()
