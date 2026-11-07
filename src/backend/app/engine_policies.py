"""Versioned engine policy references; explicit seeding never happens at startup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import Connection, Row, insert, select, text

from app.db.tables.strategy import engine_policies


class SystemComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    version_no: StrictInt = Field(ge=1)


class EnginePolicyReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_no: StrictInt = Field(ge=1)
    confidence: dict[str, Any]
    system_components: list[SystemComponent]

    @model_validator(mode="after")
    def fixed_mvp(self) -> EnginePolicyReference:
        if self.confidence != {
            "weights": {
                "data_completeness": "0.5",
                "dimension_agreement": "0.3",
                "condition_margin": "0.2",
            },
            "levels": {"high": "0.70", "medium": "0.40"},
            "missing_component": "zero_without_renormalization",
            "margin": {
                "scale_order": ["declared", "atr14", "abs_threshold"],
                "maximum": "1",
                "default_weight": "1",
            },
        }:
            raise ValueError("unsupported_confidence_policy")
        keys = [c.key for c in self.system_components]
        if len(set(keys)) != len(keys) or set(keys) != {
            "gate_tradability",
            "veto_risk_announcement",
            "ctx_market_regime",
            "hold_risk_monitor",
        }:
            raise ValueError("invalid_system_components")
        return self

    def content(self) -> dict[str, Any]:
        return self.model_dump(exclude={"version_no"})

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.content(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()


def seed(conn: Connection, reference: EnginePolicyReference) -> bool:
    conn.execute(text("SELECT pg_advisory_xact_lock(76, 16)"))
    row = conn.execute(
        select(engine_policies).where(engine_policies.c.version_no == reference.version_no)
    ).one_or_none()
    expected = {**reference.content(), "content_sha256": reference.digest()}
    if row:
        if row.config != expected:
            raise ValueError("engine_policy_version_hash_conflict")
        return False
    conn.execute(insert(engine_policies).values(version_no=reference.version_no, config=expected))
    return True


def check(conn: Connection, reference: EnginePolicyReference) -> None:
    """Read-only same-version guard; missing seed is handled by the worker as a gap."""
    config = conn.execute(
        select(engine_policies.c.config).where(engine_policies.c.version_no == reference.version_no)
    ).scalar_one_or_none()
    if config is not None and config != {
        **reference.content(),
        "content_sha256": reference.digest(),
    }:
        raise ValueError("engine_policy_version_hash_conflict")


def load(directory: Path) -> EnginePolicyReference:
    from app.reference_files import load_reference_file

    return EnginePolicyReference.model_validate(
        load_reference_file(directory, "engine_policy.yaml").model_dump()
    )


def latest(conn: Connection) -> Row[Any] | None:
    row = conn.execute(
        select(engine_policies).order_by(engine_policies.c.version_no.desc()).limit(1)
    ).first()
    if row is not None:
        content = {k: v for k, v in row.config.items() if k != "content_sha256"}
        reference = EnginePolicyReference.model_validate({"version_no": row.version_no, **content})
        if reference.digest() != row.config.get("content_sha256"):
            raise ValueError("engine_policy_stored_hash_invalid")
    return row


def main() -> None:
    import argparse

    from sqlalchemy import create_engine

    from app.config import Settings

    parser = argparse.ArgumentParser(
        description="Explicit engine policy seed (target is caller supplied)"
    )
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    settings = Settings(_env_file=None)
    engine = create_engine(args.database_url)
    try:
        with engine.begin() as conn:
            inserted = seed(conn, load(settings.config_dir))
        print("engine_policy_seed_inserted=" + str(int(inserted)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
