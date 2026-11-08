# ruff: noqa: ANN401
"""T-A18 immutable content binding. No approval or human-proof issuance entrypoint."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, update

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
    if (
        not isinstance(binding, dict)
        or not binding.get("content_sha256")
        or not binding.get("version_id")
    ):
        return {}
    return binding


def stale_reason(binding: dict[str, Any], current: uuid.UUID | None, digest: str) -> str | None:
    if not binding.get("content_sha256") or not binding.get("version_id"):
        return "legacy_unbound"
    if binding["version_id"] != str(current):
        return "new_version"
    if binding["content_sha256"] != digest:
        return "content_changed"
    return None


def is_stale(binding: dict[str, Any], current: uuid.UUID | None, digest: str) -> bool:
    return stale_reason(binding, current, digest) is not None


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
        raise AppError(
            ErrorCode.PROMOTION_GATES_NOT_MET,
            details={"gates": [{"gate": "G7", "result": "skipped"}]},
        )
    require_current(binding, current, digest)
    if (
        row.target_strategy_version_id != version_id
        or row.decision != "approved"
        or row.reviewer_id is None
        or row.reviewed_at is None
    ):
        raise AppError(
            ErrorCode.PROMOTION_GATES_NOT_MET,
            details={"gates": [{"gate": "G7", "result": "skipped"}]},
        )


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
    reason = stale_reason(
        binding, current_version(conn, card.id), content_sha256(card_version, version)
    )
    return {
        "review_id": str(row.id),
        "card_id": str(card.id),
        "card_key": card.key,
        "version_id": str(version.id) if binding else None,
        "version_no": version.version_no,
        "content_sha256": binding.get("content_sha256"),
        "lifecycle": version.lifecycle,
        "stale": reason is not None,
        "stale_reason": reason,
        "decision": row.decision,
        "gates": [
            {"gate": f"G{i}", "result": gate_map.get(f"G{i}", "skipped")} for i in range(1, 7)
        ],
        "g7": row.decision,
        "submitted_by": binding.get("submitted_by"),
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
        raise AppError(
            ErrorCode.PROMOTION_GATES_NOT_MET,
            details={"gates": [{"gate": g, "result": gate_map.get(g, "skipped")} for g in failed]},
        )
    unacknowledged = [
        f"G{i}"
        for i in range(1, 7)
        if gate_map.get(f"G{i}") == "warn" and f"G{i}" not in ack_warn_gates
    ]
    if unacknowledged:
        raise AppError(ErrorCode.PROMOTION_WARN_UNACKNOWLEDGED, details={"gates": unacknowledged})


# plan §8.1 authoritative wording list; no self-invented investment rules.
COMPLIANCE_TERMS = ("保证", "必涨", "稳赚", "牛股", "金股", "目标价")


def lint(text: str) -> None:
    import unicodedata

    normalized = unicodedata.normalize("NFKC", text)
    terms = [term for term in COMPLIANCE_TERMS if term in normalized]
    if terms:
        raise AppError(ErrorCode.COMPLIANCE_LINT_FAILED, details={"terms": terms})


def decide(
    conn: Connection,
    owner: uuid.UUID,
    identifier: uuid.UUID,
    decision: str,
    comment: str,
    acknowledged: list[str],
    coarse_ip: str | None,
) -> dict[str, Any]:
    import datetime as dt

    from app.auth.service import audit

    row, card, card_version, version = review_context(conn, owner, identifier, lock=True)
    validate_decision(
        row,
        binding_of(row),
        current_version(conn, card.id),
        content_sha256(card_version, version),
        decision,
        acknowledged,
    )
    lint(comment)
    if decision == "approved":
        lint(json.dumps(card_version.fields, ensure_ascii=False))
    now = dt.datetime.now(dt.UTC)
    gates = [g for g in row.gate_results or [] if g["gate"] != "G7"]
    gates.append(
        {
            "gate": "G7",
            "result": "pass" if decision == "approved" else "fail",
            "detail": {"decision": decision, "reviewer_id": str(owner)},
        }
    )
    conn.execute(
        update(reviews)
        .where(reviews.c.id == identifier)
        .values(
            decision=decision,
            reviewer_id=owner,
            reviewed_at=now,
            note=comment,
            gate_results=gates,
            compliance_lint={
                **(row.compliance_lint or {}),
                "status": "pass",
                "ack_warn_gates": acknowledged,
                "human_review": {"origin": "password_login"},
            },
        )
    )
    audit(
        conn,
        action="promotion.decision",
        actor_id=owner,
        actor_role="admin",
        target_type="promotion",
        target_id=str(identifier),
        detail={
            "review_id": str(identifier),
            "reviewer_id": str(owner),
            "decision": decision,
            "ack_warn_gates": acknowledged,
            "comment": comment,
            "at": now.isoformat(),
            "source_ip_coarse": coarse_ip,
        },
    )
    updated = conn.execute(select(reviews).where(reviews.c.id == identifier)).one()
    return summary(conn, updated, card, card_version, version)


def change_lifecycle(
    conn: Connection,
    owner: uuid.UUID,
    strategy_id: uuid.UUID,
    version_id: uuid.UUID,
    to: str,
    reason: str,
    review_id: uuid.UUID | None,
    coarse_ip: str | None,
) -> dict[str, str]:
    import datetime as dt

    from app.auth.service import audit
    from app.db.tables.strategy import strategy_lifecycle_events

    card, card_version, version = version_context(conn, version_id, owner, lock=True)
    if version.strategy_id != strategy_id:
        raise AppError(ErrorCode.NOT_FOUND)
    previous = version.lifecycle
    if previous == to or previous == "retired":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
    if previous == "draft" and to == "simulating":
        if review_id is None:
            raise AppError(
                ErrorCode.PROMOTION_GATES_NOT_MET,
                details={"gates": [{"gate": "G7", "result": "skipped"}]},
            )
        row = conn.execute(select(reviews).where(reviews.c.id == review_id)).first()
        if row is None:
            raise AppError(
                ErrorCode.PROMOTION_GATES_NOT_MET,
                details={"gates": [{"gate": "G7", "result": "skipped"}]},
            )
        binding = binding_of(row)
        if row.target_strategy_version_id != version_id:
            if binding.get("card_id") == str(card.id) or row.card_version_id == card_version.id:
                require_current(
                    binding, current_version(conn, card.id), content_sha256(card_version, version)
                )
            raise AppError(
                ErrorCode.PROMOTION_GATES_NOT_MET,
                details={"gates": [{"gate": "G7", "result": "fail"}]},
            )
        row = conn.execute(select(reviews).where(reviews.c.id == review_id).with_for_update()).one()
        require_approved(
            row,
            binding_of(row),
            current_version(conn, card.id),
            content_sha256(card_version, version),
            version_id,
        )
        by_gate = {g["gate"]: g["result"] for g in row.gate_results or []}
        failed = [
            {"gate": f"G{i}", "result": by_gate.get(f"G{i}", "skipped")}
            for i in range(1, 8)
            if by_gate.get(f"G{i}") not in {"pass", "warn"}
        ]
        if by_gate.get("G7") != "pass" and not any(g["gate"] == "G7" for g in failed):
            failed.append({"gate": "G7", "result": by_gate.get("G7", "skipped")})
        if failed or (row.compliance_lint or {}).get("human_review") != {
            "origin": "password_login"
        }:
            raise AppError(
                ErrorCode.PROMOTION_GATES_NOT_MET,
                details={"gates": failed or [{"gate": "G7", "result": "fail"}]},
            )
        warnings = [
            g
            for g, result in by_gate.items()
            if g != "G7"
            and result == "warn"
            and g not in (row.compliance_lint or {}).get("ack_warn_gates", [])
        ]
        if warnings:
            raise AppError(ErrorCode.PROMOTION_WARN_UNACKNOWLEDGED, details={"gates": warnings})
    elif to == "published" and previous == "simulating":
        # This MVP does not have the plan §2.5.13 verified_live + simulation
        # evidence chain. Never equate a G7 approval with publication eligibility.
        raise AppError(
            ErrorCode.PROMOTION_GATES_NOT_MET,
            details={
                "gates": [{"gate": "G2", "result": "skipped"}, {"gate": "G6", "result": "skipped"}]
            },
        )
    elif to != "retired":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
    now = dt.datetime.now(dt.UTC)
    conn.execute(
        update(versions)
        .where(versions.c.id == version_id)
        .values(lifecycle=to, lifecycle_changed_by=owner, lifecycle_changed_at=now)
    )
    conn.execute(
        insert(strategy_lifecycle_events).values(
            strategy_version_id=version_id,
            from_state=previous,
            to_state=to,
            reason=reason,
            trigger="admin",
            actor_id=owner,
            at=now,
        )
    )
    audit(
        conn,
        action="strategy.lifecycle",
        actor_id=owner,
        actor_role="admin",
        target_type="strategy_version",
        target_id=str(version_id),
        detail={
            "from": previous,
            "to": to,
            "review_id": str(review_id) if review_id else None,
            "reason": reason,
            "at": now.isoformat(),
            "source_ip_coarse": coarse_ip,
        },
    )
    return {"from": previous, "to": to}
