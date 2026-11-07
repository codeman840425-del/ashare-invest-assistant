"""Transactional draft-only formal import and deterministic generated files.

Caller owns the transaction; never imports on startup implicitly. G1–G7 and live
verification are NOT granted by a research handoff or successful fixture replay.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert

from app.db.tables.strategy import (
    feature_catalog,
    strategies,
    strategy_card_versions,
    strategy_cards,
    strategy_versions,
)
from app.strategy.cards.models import PendingImport
from app.strategy.cards.preflight import preflight


def digest(value: Any) -> str:  # noqa: ANN401
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def validate_batch(
    documents: list[str], registry: dict[str, dict[str, Any]]
) -> list[PendingImport]:
    staged, errors = preflight(documents, registry)
    if errors:
        raise ValueError(
            json.dumps({"code": "CARD_IMPORT_INVALID", "issues": errors}, ensure_ascii=False)
        )
    return staged


def generated_payload(item: PendingImport) -> dict[str, Any]:
    return {
        "key": item.identity.key,
        "version_no": item.identity.version_no,
        "source_hash": item.source_hash,
        "narrative": item.narrative,
        **item.blocks,
    }


def generate_files(staged: list[PendingImport], directory: Path) -> list[Path]:
    # Validate every destination before writing any file. Keys were regex-validated.
    files = {
        directory / (item.identity.key + ".yaml"): yaml.safe_dump(
            generated_payload(item), allow_unicode=True, sort_keys=True
        )
        for item in staged
    }
    for path, content in files.items():
        if path.exists() and path.read_text() != content:
            raise ValueError("immutable generated version conflict")
    directory.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    return list(files)


def import_batch(
    conn: Connection, documents: list[str], registry: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    staged = validate_batch(documents, registry)
    # A transaction-scoped lock serializes formal global-key imports, not user activity.
    from sqlalchemy import text

    conn.execute(text("select pg_advisory_xact_lock(714071)"))
    result = []
    for item in staged:
        key, number = item.identity.key, item.identity.version_no
        card: dict[str, Any] = copy.deepcopy(item.blocks["strategy-card"])
        spec: dict[str, Any] = copy.deepcopy(item.blocks.get("strategy-spec") or {})
        card_head = conn.execute(select(strategy_cards).where(strategy_cards.c.key == key)).first()
        if card_head is not None and card_head.owner_user_id is not None:
            raise ValueError("global_card_key_owned_by_private_user")
        card_id = card_head.id if card_head else uuid.uuid4()
        fields = {**card, "narrative": item.narrative, "source_hash": item.source_hash}
        if card_head:
            previous = conn.execute(
                select(strategy_card_versions).where(
                    strategy_card_versions.c.card_id == card_id,
                    strategy_card_versions.c.version_no == number,
                )
            ).first()
            if previous:
                if previous.fields != fields:
                    raise ValueError("immutable_card_version_conflict")
                version = conn.execute(
                    select(strategy_versions).where(
                        strategy_versions.c.card_version_id == previous.id
                    )
                ).first()
                result.append(
                    {
                        "key": key,
                        "card_id": str(card_id),
                        "card_version_id": str(previous.id),
                        "strategy_id": str(version.strategy_id) if version else "",
                        "version_id": str(version.id) if version else "",
                    }
                )
                continue
        if not card_head:
            conn.execute(
                insert(strategy_cards).values(
                    id=card_id,
                    key=key,
                    title=item.identity.name,
                    completeness="draft",
                    source_kind="builtin",
                    owner_user_id=None,
                )
            )
        card_version_id = uuid.uuid4()
        conn.execute(
            insert(strategy_card_versions).values(
                id=card_version_id,
                card_id=card_id,
                version_no=number,
                fields=fields,
                field_epistemic=card.get("epistemic"),
                references=card.get("refs", []),
            )
        )
        conn.execute(
            update(strategy_cards)
            .where(strategy_cards.c.id == card_id)
            .values(current_version_id=card_version_id)
        )
        identifier = uuid.uuid4()
        strategy = conn.execute(select(strategies).where(strategies.c.key == key)).first()
        if strategy is not None and strategy.owner_user_id is not None:
            raise ValueError("global_strategy_key_owned_by_private_user")
        strategy_id = strategy.id if strategy else uuid.uuid4()
        if not strategy:
            conn.execute(
                insert(strategies).values(
                    id=strategy_id,
                    key=key,
                    name=item.identity.name,
                    owner_user_id=None,
                    horizons=card["horizons"],
                )
            )
        configuration = {
            **spec,
            "mount_policy": card.get("mount_policy", "user"),
            "source_hash": item.source_hash,
            "validation": item.blocks.get("validation"),
            "gates_missing": [f"G{n}:promotion_review_pending" for n in range(1, 8)],
        }
        conn.execute(
            insert(strategy_versions).values(
                id=identifier,
                strategy_id=strategy_id,
                version_no=number,
                config=configuration,
                config_hash=digest(configuration),
                card_version_id=card_version_id,
                kind=spec.get("kind", "rule_template"),
                params_schema=spec.get("params_schema"),
                param_hash=digest(
                    {
                        name: value["default"]
                        for name, value in spec.get("params_schema", {}).items()
                    }
                ),
                feature_set_version="T-R15-feature-spec-1.1.11",
                lifecycle="draft",
            )
        )
        conn.execute(
            update(strategies)
            .where(strategies.c.id == strategy_id)
            .values(current_version_id=identifier)
        )
        needed = {need["feature_key"] for need in card["data_needs"]}
        for name in needed:
            definition = registry[name]
            values = {
                column: definition.get(column)
                for column in ("source", "derivation", "unit", "adjust", "frequency", "pit_rule")
            }
            conn.execute(
                insert(feature_catalog)
                .values(
                    feature_key=name,
                    status="declared",
                    owner="T-R15",
                    pipeline_version="feature-spec-1.1.11",
                    **values,
                )
                .on_conflict_do_nothing(index_elements=[feature_catalog.c.feature_key])
            )
        result.append(
            {
                "key": key,
                "card_id": str(card_id),
                "card_version_id": str(card_version_id),
                "strategy_id": str(strategy_id),
                "version_id": str(identifier),
            }
        )
    return result
