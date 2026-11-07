# ruff: noqa: ANN401
"""T-A13 reviewed display metadata; never infers fields or changes G2 status."""

from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, func, or_
from sqlalchemy.dialects.postgresql import insert

from app.db.tables.strategy import feature_catalog
from app.schemas.enums import Dimension, EpistemicType


class FeatureMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    feature_key: str = Field(strict=True, pattern=r"^f\.[a-z0-9_]+$")
    description: str | None = Field(default=None, strict=True)
    dimension: Dimension | None = None
    warmup_bars: int | None = Field(default=None, strict=True, ge=0)
    available_at: str | None = Field(default=None, strict=True)
    epistemic_type: EpistemicType | None = None
    spec_ref: str | None = Field(default=None, strict=True, pattern=r"^F[0-9]+$")


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    features: list[FeatureMeta]


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader: UniqueLoader, node: Any) -> Any:
    pairs = loader.construct_pairs(node)
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_metadata_field")
        result[key] = value
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def validate_keys(rows: list[FeatureMeta], registry: dict[str, dict[str, Any]]) -> None:
    keys = [row.feature_key for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_metadata_feature_key")
    if set(keys) - registry.keys():
        raise ValueError("unknown_metadata_feature_key")


def load_metadata(
    document: str, catalog: str, registry: dict[str, dict[str, Any]]
) -> list[FeatureMeta]:
    if len(document) > 1_000_000:
        raise ValueError("metadata_size_limit")
    loader = UniqueLoader(document)
    try:
        parsed = loader.get_single_data()
    finally:
        loader.dispose()
    rows = Document.model_validate(parsed).features
    validate_keys(rows, registry)
    refs = {
        key: reference
        for heading in re.findall(r"^### F[0-9]+[^\n]*", catalog, re.M)
        for reference, key in re.findall(r"(F[0-9]+) `(f\.[a-z0-9_]+)`", heading)
    }
    for row in rows:
        if row.spec_ref is not None and refs.get(row.feature_key) != row.spec_ref:
            raise ValueError("metadata_spec_ref_mismatch")
    return rows


def import_metadata(
    conn: Connection, rows: list[FeatureMeta], registry: dict[str, dict[str, Any]]
) -> None:
    validate_keys(rows, registry)  # fail before any write, including programmatic callers
    for row in rows:
        definition = registry[row.feature_key]
        metadata = {
            "description": row.description,
            "dimension": row.dimension,
            "warmup_bars": row.warmup_bars,
            "epistemic_type": row.epistemic_type,
        }  # Display metadata must not overwrite canonical PIT semantics.
        statement = insert(feature_catalog).values(
            feature_key=row.feature_key,
            **{
                key: definition.get(key)
                for key in ("source", "derivation", "unit", "adjust", "frequency", "pit_rule")
            },
            status="declared",
            owner="T-R17",
            pipeline_version="feature-spec-1.1.11",
            **metadata,
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[feature_catalog.c.feature_key],
                set_={**metadata, "updated_at": func.now()},
                where=or_(
                    *(
                        feature_catalog.c[key].is_distinct_from(getattr(statement.excluded, key))
                        for key in metadata
                    )
                ),
            )
        )
