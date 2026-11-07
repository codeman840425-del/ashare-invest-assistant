"""Reviewed T-R18 provenance, not a research recommendation→runtime upgrade shortcut."""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from app.db.tables.strategy import feature_catalog
from app.strategy.cards.feature_meta import UniqueLoader

DOC_KEYS = frozenset({"f.close_qfq", "f.high_qfq", "f.low_qfq", "f.list_days", "f.np_yoy_latest"})
DECLARED_KEYS = frozenset({"f.amount", "f.main_net_20d", "f.market_regime", "f.ind_rs20"})


class MatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    feature_key: str = Field(pattern=r"^f\.[a-z0-9_]+$")
    spec_ref: str = Field(pattern=r"^F[0-9]+$")
    current_status: Literal["declared"]
    recommendation: Literal["verified_doc_conditional", "keep_declared"]
    evidence: str
    quote: str
    formula: str
    unit: str
    available_at: str
    pit: str
    importable_if: str
    gaps: list[str]


class SourceMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    doc_urls: dict[str, str]
    features: list[MatrixRow]


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["declared", "verified_doc"]
    ceiling: Literal["simulating"] | None
    basis: dict[str, Any]
    matrix: MatrixRow
    source_matrix_sha256: str
    pit_rule: dict[str, Any] | None


def load_reviews(registry: dict[str, dict[str, Any]], document: str | None) -> dict[str, Review]:
    scoped = {key for key, row in registry.items() if row.get("status_basis")}
    if not scoped:
        return {}
    if document is None:
        raise ValueError("source_matrix_required")
    loader = UniqueLoader(document)
    try:
        matrix = SourceMatrix.model_validate(loader.get_single_data())
    finally:
        loader.dispose()
    keys = [row.feature_key for row in matrix.features]
    if len(keys) != len(set(keys)) or set(keys) != DOC_KEYS | DECLARED_KEYS or scoped != set(keys):
        raise ValueError("source_matrix_key_set_mismatch")
    reviews = {}
    for row in matrix.features:
        definition = registry[row.feature_key]
        basis = definition["status_basis"]
        status = definition.get("status")
        if basis.get("matrix") != "T-R18_source_matrix.yaml#" + row.feature_key:
            raise ValueError("source_matrix_reference_mismatch")
        expected = "verified_doc" if row.feature_key in DOC_KEYS else "declared"
        if status != expected or row.recommendation != (
            "verified_doc_conditional" if row.feature_key in DOC_KEYS else "keep_declared"
        ):
            raise ValueError("reviewed_source_status_mismatch")
        if basis.get("ceiling") != ("simulating" if row.feature_key in DOC_KEYS else None):
            raise ValueError("reviewed_source_ceiling_mismatch")
        pit = definition.get("pit_rule")
        # Canonical PIT remains F22's next open day, not the obsolete visible_at commentary.
        if (
            row.feature_key == "f.np_yoy_latest"
            and (pit or {}).get("available_at") != "next_trading_day(plrq) 09:30"
        ):
            raise ValueError("reviewed_np_visibility_mismatch")
        reviews[row.feature_key] = Review(
            status=status,
            ceiling=basis.get("ceiling"),
            basis=copy.deepcopy(basis),
            matrix=row,
            source_matrix_sha256=hashlib.sha256(document.encode()).hexdigest(),
            pit_rule=copy.deepcopy(pit),
        )
    return reviews


def persist_reviews(
    conn: Connection, registry: dict[str, dict[str, Any]], reviews: dict[str, Review]
) -> None:
    for key, review in reviews.items():
        definition = registry[key]
        old = conn.execute(
            select(feature_catalog.c.status).where(feature_catalog.c.feature_key == key)
        ).scalar_one_or_none()
        if old is not None and old not in {"declared", review.status}:
            raise ValueError("existing_source_status_requires_review")
        source = copy.deepcopy(definition.get("source"))
        source = dict(source) if isinstance(source, dict) else {"origin": source}
        source["reviewed_document"] = review.model_dump(mode="json")
        statement = insert(feature_catalog).values(
            feature_key=key,
            status=review.status,
            source=source,
            owner="T-R18",
            pipeline_version="feature-spec-1.1.12",
            **{
                field: definition.get(field)
                for field in ["derivation", "unit", "adjust", "frequency", "pit_rule"]
            },
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[feature_catalog.c.feature_key],
                set_={
                    "status": statement.excluded.status,
                    "source": statement.excluded.source,
                    "pipeline_version": statement.excluded.pipeline_version,
                },
                where=feature_catalog.c.status.is_distinct_from(statement.excluded.status)
                | feature_catalog.c.source.is_distinct_from(statement.excluded.source),
            )
        )


def source_issues(
    registry: dict[str, dict[str, Any]], required: set[str], target: str
) -> list[dict[str, str]]:
    if target not in {"simulating", "published", "observing"}:
        raise ValueError("source_target_not_defined")
    issues = []
    for key in sorted(required):
        row = registry.get(key, {})
        status = row.get("status")
        review = (
            (row.get("source") or {}).get("reviewed_document")
            if isinstance(row.get("source"), dict)
            else None
        )
        issue = None
        if status not in {"verified_doc", "verified_live"}:
            issue = "feature_not_verified_doc_or_live"
        elif key in DOC_KEYS | DECLARED_KEYS and (not review or review.get("status") != status):
            issue = "reviewed_source_missing_or_status_conflict"
        elif status == "verified_doc" and target != "simulating":
            issue = "verified_doc_simulating_only"
        elif review and review.get("ceiling") == "simulating" and target != "simulating":
            issue = "reviewed_source_lifecycle_ceiling"
        if issue:
            issues.append({"path": key, "issue": issue})
    return issues


def required_features(spec: dict[str, Any], _card: dict[str, Any]) -> set[str]:
    # Preserve the existing G2 rule-feature scope. data_needs also contains the
    # separate tradability adapters; T-R18 does not reclassify those whitelist inputs.
    return {key for rule in spec.get("rules", []) for key in rule.get("required_features", [])}
