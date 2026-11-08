# ruff: noqa: ANN401
"""T-A18 immutable content binding. No approval or human-proof issuance entrypoint."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import Connection, Engine, insert, select

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.strategy import (
    strategies,
)
from app.db.tables.strategy import (
    strategy_card_versions as cv,
)
from app.db.tables.strategy import (
    strategy_cards as cards,
)
from app.db.tables.strategy import (
    strategy_promotion_reviews as reviews,
)
from app.db.tables.strategy import (
    strategy_versions as versions,
)
from app.strategy.promotions import prepare, public_review

DECISIONS = frozenset({"pending", "approved", "rejected", "changes_requested"})


def content_sha256(card: Any, version: Any) -> str:
    # Hash actual JSON, not a mutable client-supplied/source/config hash field.
    payload = {
        "card_fields": card.fields,
        "field_epistemic": card.field_epistemic,
        "references": card.references,
        "config": version.config,
        "params_schema": version.params_schema,
        "rule_snippet_refs": version.rule_snippet_refs,
        "feature_set_version": version.feature_set_version,
        "kind": version.kind,
        "code_entry": version.code_entry,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def version_context(
    conn: Connection, version_id: uuid.UUID, owner: uuid.UUID, *, lock: bool = False
) -> tuple[Any, Any, Any]:
    # Card header is the serialization point for requests and latest-version changes.
    query = (
        select(cards)
        .join(cv, cv.c.card_id == cards.c.id)
        .join(versions, versions.c.card_version_id == cv.c.id)
        .join(strategies, strategies.c.id == versions.c.strategy_id)
        .where(
            versions.c.id == version_id,
            cards.c.owner_user_id.is_(None) | (cards.c.owner_user_id == owner),
            strategies.c.owner_user_id.is_(None) | (strategies.c.owner_user_id == owner),
        )
    )
    if lock:
        query = query.with_for_update(of=cards)
    card = conn.execute(query).first()
    if card is None:
        raise AppError(ErrorCode.NOT_FOUND)
    vq = select(versions).where(versions.c.id == version_id)
    if lock:
        vq = vq.with_for_update()
    version = conn.execute(vq).one()
    cq = select(cv).where(cv.c.id == version.card_version_id)
    if lock:
        cq = cq.with_for_update()
    card_version = conn.execute(cq).one()
    return card, card_version, version


def current_version(conn: Connection, card_id: uuid.UUID) -> uuid.UUID | None:
    return conn.execute(
        select(versions.c.id)
        .join(cv, cv.c.id == versions.c.card_version_id)
        .where(cv.c.card_id == card_id)
        .order_by(cv.c.version_no.desc(), versions.c.version_no.desc(), versions.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def binding_of(row: Any) -> dict[str, Any]:
    binding = (row.compliance_lint or {}).get("binding")
    if not isinstance(binding, dict) or not binding.get("content_sha256"):
        # Never bless historical approvals by manufacturing an old content hash.
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "legacy_review_binding_missing"})
    return binding


def is_stale(binding: dict[str, Any], current: uuid.UUID | None, digest: str) -> bool:
    return binding.get("version_id") != str(current) or binding.get("content_sha256") != digest


def require_current(binding: dict[str, Any], current: uuid.UUID | None, digest: str) -> None:
    if is_stale(binding, current, digest):
        raise AppError(
            ErrorCode.PROMOTION_STALE,
            details={"current_version_id": str(current) if current else None},
        )


def require_approved(
    row: Any, binding: dict[str, Any], current: uuid.UUID | None, digest: str, version_id: uuid.UUID
) -> None:
    if row is None:
        raise AppError(ErrorCode.PROMOTION_GATES_NOT_MET, details={"gates": ["G7"]})
    require_current(binding, current, digest)
    if (
        row.target_strategy_version_id != version_id
        or row.decision != "approved"
        or row.reviewer_id is None
        or row.reviewed_at is None
    ):
        raise AppError(ErrorCode.PROMOTION_GATES_NOT_MET, details={"gates": ["G7"]})


def request_review(
    conn: Connection,
    owner: uuid.UUID,
    card_id: uuid.UUID,
    version_id: uuid.UUID,
    settings: Settings,
) -> tuple[uuid.UUID, bool]:
    card, card_version, version = version_context(conn, version_id, owner, lock=True)
    if card.id != card_id:
        raise AppError(ErrorCode.NOT_FOUND)
    if version.lifecycle != "draft":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
    current = current_version(conn, card.id)
    if current != version.id:
        raise AppError(ErrorCode.PROMOTION_STALE, details={"current_version_id": str(current)})
    digest = content_sha256(card_version, version)
    candidates = conn.execute(
        select(reviews)
        .where(reviews.c.target_strategy_version_id == version_id, reviews.c.decision == "pending")
        .order_by(reviews.c.created_at, reviews.c.id)
    ).all()
    for row in candidates:
        binding = (row.compliance_lint or {}).get("binding", {})
        if binding.get("card_id") == str(card_id) and not is_stale(binding, current, digest):
            return row.id, False
    identifier = uuid.uuid4()
    stat = {"value": None, "n": 0, "window": "120 trading days", "small_sample": True}
    conn.execute(
        insert(reviews).values(
            id=identifier,
            card_version_id=card_version.id,
            target_strategy_version_id=version_id,
            decision="pending",
            fixture_runs=[],
            gate_results=[
                {"gate": f"G{i}", "result": "skipped", "detail": {"issue": "execution_pending"}}
                for i in range(1, 8)
            ],
            g6_report={
                "trigger_rate": stat,
                "coverage": stat,
                "max_jaccard": None,
                "max_jaccard_null_reason": "no_history",
                "quota_delta_per_min": 0,
            },
            compliance_lint={
                "status": "execution_pending",
                "binding": {
                    "card_id": str(card_id),
                    "version_id": str(version_id),
                    "content_sha256": digest,
                    "submitted_by": str(owner),
                },
            },
        )
    )
    return identifier, True


def execute_review(
    engine: Engine, owner: uuid.UUID, identifier: uuid.UUID, settings: Settings
) -> None:
    # Runs only after the request transaction commits. A stale/past decision is
    # never re-run, rebound, approved, or promoted. Process interruption leaves
    # explicit skipped gates, not invented success; no automatic retry.
    with engine.begin() as conn:
        row, card, card_version, version = review_context(conn, owner, identifier, lock=True)
        if row.decision != "pending" or is_stale(
            binding_of(row), current_version(conn, card.id), content_sha256(card_version, version)
        ):
            return
        if (row.compliance_lint or {}).get("status") != "execution_pending":
            return
        prepare(
            conn, owner, card.id, settings, version_id=version.id, existing_review_id=identifier
        )


def review_context(
    conn: Connection, owner: uuid.UUID, review_id: uuid.UUID, *, lock: bool = False
) -> tuple[Any, Any, Any, Any]:
    row = conn.execute(select(reviews).where(reviews.c.id == review_id)).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    card, card_version, version = version_context(
        conn, row.target_strategy_version_id, owner, lock=lock
    )
    if lock:
        row = conn.execute(select(reviews).where(reviews.c.id == review_id).with_for_update()).one()
    return row, card, card_version, version


def summary(
    conn: Connection, row: Any, card: Any, card_version: Any, version: Any
) -> dict[str, Any]:
    binding = binding_of(row)
    gate_map = {g["gate"]: g["result"] for g in row.gate_results or []}
    return {
        "review_id": str(row.id),
        "card_id": str(card.id),
        "card_key": card.key,
        "version_id": str(version.id),
        "version_no": version.version_no,
        "content_sha256": binding["content_sha256"],
        "lifecycle": version.lifecycle,
        "stale": is_stale(
            binding, current_version(conn, card.id), content_sha256(card_version, version)
        ),
        "decision": row.decision,
        "gates": [
            {"gate": f"G{i}", "result": gate_map.get(f"G{i}", "skipped")} for i in range(1, 7)
        ],
        "g7": row.decision,
        "submitted_by": binding["submitted_by"],
        "submitted_at": row.created_at,
        "reviewer_id": str(row.reviewer_id) if row.reviewer_id else None,
        "decided_at": row.reviewed_at,
    }


def detail(conn: Connection, owner: uuid.UUID, review_id: uuid.UUID) -> dict[str, Any]:
    row, card, card_version, version = review_context(conn, owner, review_id)
    item = summary(conn, row, card, card_version, version)
    return {
        k: v
        for k, v in {**item, **public_review(row)}.items()
        if k not in {"gates", "g7", "lifecycle", "card_key"}
    }


def validate_decision(
    row: Any,
    binding: dict[str, Any],
    current: uuid.UUID | None,
    digest: str,
    decision: str,
    ack_warn_gates: list[str],
) -> None:
    """Validation only; cannot establish G7 or mutate a review."""
    require_current(binding, current, digest)
    if row.decision != "pending":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
    if decision != "approved":
        return
    gate_map = {g["gate"]: g["result"] for g in row.gate_results or []}
    failed = [f"G{i}" for i in range(1, 7) if gate_map.get(f"G{i}") not in {"pass", "warn"}]
    if failed:
        raise AppError(ErrorCode.PROMOTION_GATES_NOT_MET, details={"gates": failed})
    unacknowledged = [
        f"G{i}"
        for i in range(1, 7)
        if gate_map.get(f"G{i}") == "warn" and f"G{i}" not in ack_warn_gates
    ]
    if unacknowledged:
        raise AppError(ErrorCode.PROMOTION_WARN_UNACKNOWLEDGED, details={"gates": unacknowledged})
