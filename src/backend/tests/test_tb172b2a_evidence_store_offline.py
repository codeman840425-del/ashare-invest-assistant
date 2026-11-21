"""T-A202：纯函数合成材料校验，不接触网络或数据库。"""

# ruff: noqa: S101
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pytest

from app.features import horizon_evidence_store as store

U = str(UUID(int=1723))
D = "2026-11-15"
T = "2026-11-15T09:00:00+00:00"
SHA = "a" * 64
# 固定合成证据包；占位符只用于共享日期、UUID 与材料摘要。
MATERIALS: dict[str, dict[str, Any]] = json.loads(
    """
{
  "calendar": {"is_open":true, "coverage_start":"@D", "coverage_end":"@D",
    "source_version":"v1", "sha256":"@SHA", "overlap_check":{"synthetic":true}},
  "daily_bar": {"open":null, "high":null, "low":null, "close":null, "pre_close":null,
    "volume":null, "amount":null, "is_suspended":null, "price_unit":null,
    "volume_unit":null, "amount_unit":null, "source":null, "source_licence_id":null,
    "fetched_at":null, "raw_fields":{"synthetic":true}, "raw_units":{"volume":null},
    "code":"SYN", "trade_date":"@D", "adj_type":"none", "hash":"material"},
  "ex_rights": {"code":"SYN", "ex_date":"@D", "cash_per_share":"0", "rights_price":"0",
    "bonus_ratio":"0", "rights_ratio":"0", "snapshot_sha256":"@SHA",
    "source_version":"v1", "version_hash":"@SHA"},
  "adjust_factor": {"date":"@D", "value":"1", "snapshot_sha256":"@SHA",
    "transform_version":"v1", "algo_audit":{"synthetic":true},
    "integrity_audit":{"synthetic":true}, "coverage_start":"@D", "coverage_end":"@D",
    "trade_dates":[], "issues":[]},
  "feature": {"values":{"x":null}, "units":{"x":null}, "raw_values":{"x":null},
    "transforms":{"x":"identity"}, "window":["@D","@D"], "qfq_anchor":"@D",
    "as_of":"@T", "d":null, "dependency_ids":["@U"], "evidence_ids":["@U"],
    "feature_set_version":"v1"},
  "proof": {"code":"SYN", "trade_date":"@D", "source":"fake", "licence_id":null,
    "user_id":"@U", "version_hash":"@SHA", "source_version":"v1", "sha256":"@SHA"},
  "batch": {"run_id":"@U", "owner_id":null, "licence_id":null, "members":[["@U","SYN"]],
    "status":"ok", "finished_at":"@T", "available_at":"@T", "issues":[],
    "kind":"daily_batch", "step":"daily_bars.fetch", "run_date":"@D"}
}
""".replace("@D", D)
    .replace("@T", T)
    .replace("@U", U)
    .replace("@SHA", SHA)
)
PROOF, BATCH = MATERIALS["proof"], MATERIALS["batch"]
PAYLOADS = {k: p for k, p in MATERIALS.items() if k not in {"proof", "batch"}}
EMPTY_ARRAYS = {"adjust_factor": ["trade_dates", "issues"], "batch": ["members", "issues"]}
CASES = [(kind, key) for kind, payload in MATERIALS.items() for key in payload]


def validate(kind: str, payload: dict[str, Any], available_at: datetime | None = None) -> None:
    if kind == "proof":
        store.validate_proof(
            payload, available_at=available_at, is_final=None, proof_kind="synthetic"
        )
    elif kind == "batch":
        store.validate_batch(payload)
    else:
        store.validate_payload(
            kind,
            payload,
            dependency_ids=[UUID(U)],
            transform_version="v1",
            available_at=available_at,
        )


@pytest.mark.parametrize(("kind", "key"), CASES)
@pytest.mark.parametrize("mode", ["missing", "null", "empty"])
def test_payload_required_nullable_empty(kind: str, key: str, mode: str) -> None:
    validate(kind, deepcopy(MATERIALS[kind]))
    p = deepcopy(MATERIALS[kind])
    allowed = mode == "null" and MATERIALS[kind][key] is None
    allowed |= mode == "empty" and key in EMPTY_ARRAYS.get(kind, [])
    if mode == "missing":
        del p[key]
    else:
        p[key] = (
            None
            if mode == "null"
            else ({} if isinstance(p[key], dict) else [] if isinstance(p[key], list) else "")
        )
    with nullcontext() if allowed else pytest.raises(store.EvidenceRejected):
        validate(kind, p)


@pytest.mark.parametrize("bad", ["missing", None, ""])
@pytest.mark.parametrize("kind", ["calendar", "proof"])
def test_persisted_receipt_gate(bad: object, kind: str) -> None:
    p = {**MATERIALS[kind], "persisted_receipt": bad}
    if bad == "missing":
        del p["persisted_receipt"]
    with pytest.raises(store.EvidenceRejected):
        validate(kind, p, datetime.fromisoformat(T))


@pytest.mark.parametrize(
    ("kind", "source", "scope"),
    [
        ("vendor_factor", "fake", "synthetic"),
        ("unknown", "fake", "synthetic"),
        ("daily_bar", "tdx_local", "per_licence"),
        ("daily_bar", "fake", "public"),
        ("daily_bar", "mairui", "synthetic"),
        ("calendar", "mairui", "per_licence"),
        ("feature", "derived", "synthetic"),
    ],
)
def test_source_scope_rejected(kind: str, source: str, scope: str) -> None:
    with pytest.raises(store.EvidenceRejected):
        store.validate_origin(kind, source, scope)


@pytest.mark.parametrize(
    ("kind", "key", "bad"),
    [
        ("calendar", "is_open", 1),
        ("calendar", "sha256", "A" * 64),
        ("calendar", "coverage_start", "2026-02-30"),
        ("daily_bar", "open", 1),
        ("daily_bar", "close", "NaN"),
        ("daily_bar", "fetched_at", "2026-11-15T09:00:00"),
        ("adjust_factor", "value", "0"),
        ("feature", "dependency_ids", ["e1"]),
        ("feature", "dependency_ids", []),
        ("feature", "transform_version", "other"),
    ],
)
def test_payload_types_and_outer_binding(kind: str, key: str, bad: object) -> None:
    with pytest.raises(store.EvidenceRejected):
        validate(kind, {**PAYLOADS[kind], key: bad})


def test_canon_fixed_vector() -> None:
    obj = {"uuid": UUID(U), "time": datetime.fromisoformat(T), "text": "中文", "nil": None}
    assert (
        store.canon_sha256(obj)
        == "8db5cc1790c2ebad4019eadc4c60621747d2d5c27922f5e8d2577841807c1987"
    )
    assert store.canon_sha256(obj) == store.canon_sha256(dict(reversed(list(obj.items()))))
    assert store.canon_sha256({"d": date.fromisoformat(D)}) == store.canon_sha256({"d": D})


VERSION_KEYS = (
    "user_id licence_id kind source scope code data_date source_key source_version payload "
    "first_seen_at available_at computed_at transform_version dependency_ids supersedes_id"
)
PROOF_KEYS = "proof is_final available_at bar_version_id"


@pytest.mark.parametrize(
    ("keys", "key"), [(s, k) for s in (VERSION_KEYS, PROOF_KEYS) for k in s.split()]
)
def test_hash_components(keys: str, key: str) -> None:
    p = dict.fromkeys(keys.split())
    assert store.canon_sha256(p) != store.canon_sha256({**p, key: "changed"})
