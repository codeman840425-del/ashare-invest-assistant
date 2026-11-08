"""Pure shared gate + TB05 transport adapter, all files synthetic and no network."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ingest.shared_gate import GateClosedError, SharedGate, limit_code

IP = "192.0.2.10"


@pytest.fixture
def gate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    root = tmp_path / "shared"
    root.mkdir(mode=0o700)
    lid, other = uuid.uuid4(), uuid.uuid4()
    (root / "policy.json").write_text(
        json.dumps(
            {
                "schema": "mairui-shared/v1",
                "egress_ip": IP,
                "licences": {str(ident): {"per_minute_limit": 2} for ident in (lid, other)},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIRUI_SHARED_STATE_DIR", str(root))
    monkeypatch.setenv("MAIRUI_SOURCE_LICENCE_ID", str(lid))
    return root, lid, other


@pytest.mark.parametrize("source", ["product_daily", "probe_tb05", "probe_tb86"])
@pytest.mark.parametrize("code", ["103", "429", "STOP"])
def test_every_source_halts_other_consumers_and_preserves_probe_counter(
    gate_env: Any, source: str, code: str
) -> None:
    root, lid, other = gate_env
    counter = root / "synthetic-tb86.count"
    original = {"schema": "T-B86/v1", "total": 0, "records": [], "halted": False}
    counter.write_text(json.dumps(original), encoding="utf-8")
    trigger = SharedGate(root, lid, source)
    with trigger:
        trigger.bind_certificate("synthetic-shared")
        if code == "STOP":
            (root / "STOP").touch()
        else:
            trigger.trip(code)
    for consumer in ("product_daily", "product_verify", "probe_tb05", "probe_tb86"):
        with pytest.raises(GateClosedError, match=r"STOP|halted"):
            SharedGate(root, lid, consumer).acquire()
    if code == "STOP":
        with pytest.raises(GateClosedError, match="STOP"):
            SharedGate(root, other, "product_daily").acquire()
    else:
        with SharedGate(root, other, "product_daily"):
            pass
    assert json.loads(counter.read_text(encoding="utf-8")) == original


def test_shared_budget_and_crash_reservation_are_not_reset(gate_env: Any) -> None:
    root, lid, _ = gate_env
    with SharedGate(root, lid, "probe_tb05") as first:
        first.bind_certificate("synthetic-shared")
        first.confirm_egress(IP)
        first.reserve(now=1000)
        first.complete(now=1000)
    with SharedGate(root, lid, "probe_tb86") as second:
        second.bind_certificate("synthetic-shared")
        second.confirm_egress(IP)
        second.reserve(now=1001)
        second.complete(now=1001)
        with pytest.raises(GateClosedError, match="budget"):
            second.reserve(now=1002)
    product = SharedGate(root, lid, "product_daily")
    product.acquire()
    product.bind_certificate("synthetic-shared")
    product.confirm_egress(IP)
    assert product.product_delay(1030) == 31
    product.reserve(now=1061)
    product.release()  # Models uncertain transport/process termination, no completion.
    before = product.state_path.read_bytes()
    assert product.lock_path.exists()
    assert product.halt_path.exists()
    with pytest.raises(GateClosedError, match="halted"):
        SharedGate(root, lid, "probe_tb05").acquire()
    assert product.state_path.read_bytes() == before
    assert json.loads(before)["inflight"] is True


def test_policy_missing_hardlink_and_ip_mismatch_fail_closed(gate_env: Any, tmp_path: Path) -> None:
    root, lid, _ = gate_env
    with pytest.raises(GateClosedError, match="policy"):
        SharedGate(root, uuid.uuid4(), "product_daily")
    with (
        SharedGate(root, lid, "product_daily") as gate,
        pytest.raises(GateClosedError, match="egress"),
    ):
        gate.confirm_egress("192.0.2.11")
    policy = root / "policy.json"
    os.link(policy, tmp_path / "synthetic-policy-link")
    with pytest.raises(GateClosedError, match="regular"):
        SharedGate(root, lid, "product_daily")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode check exercised on Linux")
def test_world_accessible_runtime_directory_is_refused(gate_env: Any) -> None:
    root, lid, _ = gate_env
    root.chmod(0o777)
    with pytest.raises(GateClosedError, match="private"):
        SharedGate(root, lid, "product_daily")


@pytest.mark.parametrize(
    "payload", ["103", "103: test", {"error": "103: test"}, {"nested": [{"error_code": 429}]}]
)
def test_body_wrapped_ip_limits_are_recognized(payload: Any) -> None:
    assert limit_code(200, payload) in {"103", "429"}


def test_tb05_real_call_adapter_sets_shared_latch_without_redirect_or_secret_output(
    gate_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probes import common

    root, lid, _ = gate_env
    gate = SharedGate(root, lid, "probe_tb05")
    gate.acquire()
    gate.confirm_egress(IP)
    calls = []
    secret = "synthetic-" + uuid.uuid4().hex
    monkeypatch.setenv("MAIRUI_LICENCE", secret)

    def request(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["allow_redirects"] is False
        calls.append(1)
        return SimpleNamespace(
            status_code=200, text='{"error":"103: test"}', history=[], headers={}
        )

    context = common.RunCtx(
        dry_run=False,
        base="https://api.mairuiapi.com",
        pro_base="https://pro.mairuiapi.com",
        run_id="synthetic",
        run_dir=tmp_path,
        samples_dir=tmp_path,
        stop_file=gate.stop,
        call_log=tmp_path / "synthetic.jsonl",
        min_interval=0,
        session=SimpleNamespace(request=request, close=lambda: None),
        shared_gate=gate,
    )
    monkeypatch.setattr(common, "_ctx", context)
    monkeypatch.setattr(common, "connection_stats", dict)
    try:
        with pytest.raises(common.LimitHit, match="latch"):
            common.call("synthetic", "/synthetic/{licence}")
        assert calls == [1]
        with pytest.raises(GateClosedError, match="halted"):
            SharedGate(root, lid, "product_daily").acquire()
        assert secret not in context.call_log.read_text(encoding="utf-8")
        assert secret not in gate.halt_path.read_text(encoding="utf-8")
    finally:
        gate.release()


@pytest.mark.parametrize(
    "bad",
    [
        {"licence": "synthetic-secret-not-allowed"},
        {"exclusive_lock": "synthetic-secret-not-allowed"},
    ],
)
def test_product_config_cannot_smuggle_credential_strings(tmp_path: Path, bad: Any) -> None:
    import yaml

    from app.config import ConfigError, load_yaml_dir
    from app.config_files import IngestProductDaily

    payload = {"licences": {"product_daily": IngestProductDaily().model_dump(mode="json") | bad}}
    (tmp_path / "ingest.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_yaml_dir(tmp_path)
    assert "synthetic-secret-not-allowed" not in str(error.value)
