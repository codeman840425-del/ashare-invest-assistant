"""T-B102c uses the deployed probe's state-* paths and the production app-only image shape."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import ast
import fcntl
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from app.ingest import daily_lists
from app.ingest.send_state import MinuteLedger, ledger128_total
from app.ingest.shared_gate import GateClosedError, limit_code
from selfchecks import test_tb102_governance as previous
from selfchecks.test_tb102_governance import dispatch, logs, records
from selfchecks.test_tb102b_governance import private

env = previous.env
ROOT = Path(__file__).resolve().parents[3]


def test_tb102c_app_imports_never_depend_on_excluded_probes() -> None:
    for path in (ROOT / "src/backend/app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("probes"), path
            elif isinstance(node, ast.Import):
                assert all(not item.name.startswith("probes") for item in node.names), path


def test_tb102c_dispatch_in_app_only_runtime(env: Any, tmp_path: Path) -> None:
    e = env
    product = tmp_path / "product"
    shutil.copytree(ROOT / "src/backend/app", product / "app")
    program = """
import importlib.util, datetime as dt, uuid
from pathlib import Path
from app.ingest.send_governance import Governance
assert importlib.util.find_spec("probes") is None
root=Path(__import__('sys').argv[1])
lid=uuid.UUID(__import__('sys').argv[2])
now=dt.datetime.fromisoformat(__import__('sys').argv[3])
with Governance(root,enforce=True,clock=lambda:now,licence_id=lid).dispatch(
    token=uuid.uuid4(),dataset="hslt_list",expected_day=now.date(),trading_day=True):
    pass
"""
    result = subprocess.run(  # noqa: S603 - fixed Python script, no shell/network/credential input
        [sys.executable, "-c", program, str(e.root), str(e.lid), e.now[0].isoformat()],
        cwd=product,
        env={**os.environ, "PYTHONPATH": str(product)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert len(records(e)) == 1


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("case", ["inflight", "minute", "interval"])
def test_tb102c_actual_bound_probe_filename_blocks_or_observes(
    env: Any, enforce: bool, case: str
) -> None:
    e = env
    now = e.now[0].timestamp()
    bound = e.root / "state-synthetic-binding.requests.json"
    state = {
        "calls": [now - 1] * (150 if case == "minute" else 0),
        "inflight": case == "inflight",
        "last_finished": now - 59 if case == "interval" else 0,
    }
    private(bound, state)
    # An empty UUID file must not shadow the actual T-O44 bound probe ledger.
    legacy = e.root / f"{e.lid}.requests.json"
    private(legacy, {"calls": [], "inflight": False, "last_finished": 0})
    old = legacy.read_bytes()
    if enforce:
        with pytest.raises(GateClosedError):
            dispatch(e)
        assert records(e) == e.calls == []
    else:
        dispatch(e, enforce=False)
        assert len(json.loads(bound.read_text())["calls"]) == len(state["calls"]) + 1
        assert len(e.calls) == 1
    assert legacy.read_bytes() == old
    assert (
        logs(e)[0]["snapshot"]["reason"]
        == {
            "inflight": "shared_prior_request_uncertain",
            "minute": "shared_minute_budget_exhausted",
            "interval": "shared_product_interval_not_elapsed",
        }[case]
    )


def test_tb102c_legacy_requests_still_count_with_bound_state(env: Any) -> None:
    e = env
    private(
        e.root / "state-synthetic.requests.json",
        {"calls": [], "inflight": False, "last_finished": 0},
    )
    private(e.root / f"{e.lid}.requests.json", {"calls": [], "inflight": True, "last_finished": 0})
    with pytest.raises(GateClosedError, match="lock_refused"):
        dispatch(e)
    assert records(e) == []


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102c_parseable_halt_without_code_is_stop(env: Any, enforce: bool) -> None:
    private(env.root / "state-synthetic.halt.json", {"source": "probe_tb05"})
    if enforce:
        with pytest.raises(GateClosedError, match="stop_refused"):
            dispatch(env)
        assert env.calls == []
    else:
        dispatch(env, enforce=False)
        assert len(env.calls) == 1
    assert logs(env)[0]["snapshot"]["reason"] == "probe_halt_present"


@pytest.mark.parametrize("payload", [b"103", b" 103 ", b"103:", b"429", b"429:"])
def test_tb102c_real_wire_plain_text_limit_keeps_string(
    env: Any, monkeypatch: Any, payload: bytes
) -> None:
    e = env
    monkeypatch.setenv("MAIRUI_MODE", "live")

    class Connection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def getresponse(self) -> Any:
            return SimpleNamespace(status=200, read=lambda count: payload)

        def close(self) -> None:
            pass

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    with previous.governance(e).dispatch(
        token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
    ) as permit:
        status, body = daily_lists.send(permit, daily_lists.wire, "/hslt/list/", "synthetic")
        assert isinstance(body, str)
        assert daily_lists.limited(status, body)
        assert limit_code(status, body) in {"103", "429"}


def test_tb102c_compose_observes_original_ledger_readonly() -> None:
    compose = yaml.safe_load(
        (ROOT / "deploy/compose/docker-compose.yml").read_text(encoding="utf-8")
    )
    ingest = compose["services"]["ingest"]
    target = ingest["environment"]["MAIRUI_TB86_COUNTER_PATH"]
    mount = next(
        row for row in ingest["volumes"] if isinstance(row, dict) and row["target"] == target
    )
    assert mount["type"] == "bind"
    assert mount["read_only"] is True
    assert mount["bind"]["create_host_path"] is False
    assert (
        "/home/aia/.local/state/ashare-invest-assistant/runtime/mairui-batch-T-B86.count"
        in mount["source"]
    )


def test_tb102c_vendored_probe_caps_are_readonly_and_reject_unknown(env: Any) -> None:
    path = env.root / "original.count"
    private(path, {"schema": "T-B86/v1", "total": 0, "records": [], "halted": False})
    before = path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns
    assert ledger128_total(path) == 0
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before
    private(path, {"schema": "T-B86/v1", "total": 1, "records": [], "halted": False})
    assert ledger128_total(path) is None
    assert not (env.root / "missing.count").exists()
    assert ledger128_total(env.root / "missing.count") is None


def test_tb102c_minute_rollback_only_own_unsent_preserves_probe_history(env: Any) -> None:
    e = env
    path = e.root / "state-synthetic.requests.json"
    state = {"calls": [e.now[0].timestamp() - 61], "inflight": False, "last_finished": 0}
    private(path, state)
    minute = MinuteLedger(e.root, e.lid)
    minute.read(e.now[0].timestamp())
    minute.reserve(e.now[0].timestamp())
    minute.cancel_unsent()
    assert json.loads(path.read_text()) == {
        **state,
        "calls": [],
    }  # Rolling 60s eviction stays evicted.


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102c_flock_busy_observation_is_hard_in_both_modes(env: Any, enforce: bool) -> None:
    e = env
    fd = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(GateClosedError, match="shared_control_busy"):
            dispatch(e, enforce=enforce)
        hit = logs(e)[0]
        assert hit["code"] == "shared_control_busy"
        assert hit["would_block"] is True
        assert hit["snapshot"]["lock_holder"] == os.getpid()
        assert "ledger128_total" in hit["snapshot"]
        assert "ledger_total" in hit["snapshot"]
        assert records(e) == e.calls == []
    finally:
        os.close(fd)
