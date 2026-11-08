"""T-B88: reviewed mechanical draft cases; real synthetic owner-bound HTTP/DB.

No formal cards, external source, private samples or G7 actions. The invalid
legacy worker fixture is reproduced, not silently promoted to a valid strategy.
"""

# ruff: noqa: S101, ANN401, F811
from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy import insert, select

from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import candidate_signals
from app.signals.models import SignalInput
from app.workers import daily, jobs
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import AT, persist, setup, signal  # noqa: F401
from selfchecks.test_tb76_daily import (
    test_true_evaluator_path_records_unassembled_p1_not_fake_suggestions as original_worker_case,
)


def detail(evidence_id: str) -> dict[str, Any]:
    return {
        "control": "total_exposure",
        "code": "REGIME_MISMATCH",
        "detail": {"cause": "total_exposure_at_cap"},
        "evidence_ids": [evidence_id],
    }


@pytest.mark.parametrize("nonempty", [False, True])
def test_optional_or_nonempty_detail_real_projection_and_owner(setup: Any, nonempty: bool) -> None:
    engine, client, stranger, owner, *_ = setup
    payload = signal().model_dump(mode="json")
    if nonempty:
        payload["risk_details"] = [detail(payload["evidence"][0]["id"])]
    content = SignalInput.model_validate(payload)
    result = persist(setup, content)
    assert result["id"]
    response = client.get("/api/v1/candidate-signals/" + result["id"])
    assert response.status_code == 200
    assert response.json()["evidence"]
    # Internal details must NOT invent a new public CandidateSignal field.
    assert "risk_details" not in response.json()
    assert client.get("/api/v1/candidate-signals").status_code == 200
    assert stranger.get("/api/v1/candidate-signals/" + result["id"]).status_code == 404
    with engine.connect() as conn:
        saved = conn.execute(
            select(data_snapshots.c["items"]).where(
                data_snapshots.c.id == content.snapshot_id, data_snapshots.c.user_id == owner
            )
        ).scalar_one()
    assert bool(saved["signal_input"].get("risk_details", [])) is nonempty


@pytest.mark.parametrize("bad", ["dangling", "null", "wrong_code", "malformed_input"])
def test_corrupt_synthetic_snapshot_never_silently_drops_risk_details(setup: Any, bad: str) -> None:
    engine, client, stranger, owner, *_ = setup
    content = signal()
    result = persist(setup, content)
    new_snapshot, new_signal = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        # Insert new isolated corrupt fixture; do NOT update immutable snapshots.
        saved = copy.deepcopy(
            conn.execute(
                select(data_snapshots.c["items"]).where(
                    data_snapshots.c.id == content.snapshot_id, data_snapshots.c.user_id == owner
                )
            ).scalar_one()
        )
        value = detail(content.evidence[0].id)
        if bad == "dangling":
            value["evidence_ids"] = ["synthetic-nonexistent-evidence"]
        if bad == "wrong_code":
            value["code"] = "SECTOR_EXPOSURE_EXCEEDED"
        saved["signal_input"]["risk_details"] = None if bad == "null" else [value]
        if bad == "malformed_input":
            saved["signal_input"] = []
        conn.execute(
            insert(data_snapshots).values(
                id=new_snapshot,
                user_id=owner,
                purpose="signal",
                hash=new_snapshot.hex,
                created_at=AT,
                items=saved,
            )
        )
        original = conn.execute(
            select(candidate_signals).where(candidate_signals.c.id == uuid.UUID(result["id"]))
        ).one()
        conn.execute(
            insert(candidate_signals).values(
                **{**dict(original._mapping), "id": new_signal, "snapshot_id": new_snapshot}
            )
        )
    response = client.get("/api/v1/candidate-signals/" + str(new_signal))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SIGNAL_NOT_EXPLAINABLE"
    assert stranger.get("/api/v1/candidate-signals/" + str(new_signal)).status_code == 404


def test_worker_valueerror_is_incomplete_legacy_fixture_not_missing_ma60(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []
    original = daily.conclusion

    def traced(*args: Any, **kwargs: Any) -> Any:
        try:
            return original(*args, **kwargs)
        except ValueError as exc:
            # Only record a known nonsecret diagnostic; never arbitrary inputs.
            if str(exc) == "p1_rule_evidence_counter_invalidation_missing":
                refs = kwargs["result"]["rule_refs"]
                assert {ref["role"] for ref in refs} == {"entry"}
                assert refs[0]["passed"] is None  # Real insufficient-window evaluation.
                seen.append("counter_and_invalidation_rules_absent")
            raise

    monkeypatch.setattr(daily, "conclusion", traced)
    # Keep the synthetic failed-job retry from escaping this reproduction.
    monkeypatch.setattr(jobs, "DELAYED_KEY", "T-B88:delayed:" + uuid.uuid4().hex)
    try:
        with pytest.raises(AssertionError, match="assert"):
            original_worker_case(setup)
        assert seen == ["counter_and_invalidation_rules_absent"]
    finally:
        import redis

        from selfchecks.test_tb70_replay import REDIS

        with redis.Redis.from_url(REDIS) as client:
            client.delete(jobs.DELAYED_KEY)
