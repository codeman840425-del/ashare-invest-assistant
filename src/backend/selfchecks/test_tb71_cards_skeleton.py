"""T-B71 scaffolding only: synthetic metadata, no strategy thresholds/rules/cards."""

# ruff: noqa: S101
from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from app.strategy.cards.importing import prepare_document, prepare_documents
from app.strategy.cards.models import (
    InternalCheck,
    PendingImport,
    StrategySummary,
    VersionDetail,
)

# This is deliberately NOT a complete strategy card or a runnable spec.
DOCUMENT = """# Synthetic scaffold
No formal strategy content.
```yaml strategy-card
key: fixture_metadata
version_no: 1
name: Synthetic metadata
```
"""


def test_pending_roundtrip_not_approval() -> None:
    item = prepare_document(DOCUMENT)
    assert item is not None
    assert item.status == "awaiting_formal_cards"
    assert item.persistable is False
    assert item.runnable is False
    assert item.gates_pending == ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
    assert "No formal strategy content." in item.narrative
    assert "```" not in item.narrative
    assert PendingImport.model_validate_json(item.model_dump_json()) == item
    with pytest.raises(ValidationError):
        PendingImport.model_validate(item.model_dump() | {"persistable": True})
    with pytest.raises(ValidationError):
        PendingImport.model_validate(item.model_dump() | {"runnable": True})


def test_plain_template_is_not_a_formal_card() -> None:
    assert prepare_document(DOCUMENT.replace("yaml strategy-card", "yaml")) is None
    assert prepare_documents(["# empty", "```yaml\nkey: demo\n```\n"]) == []


def test_repeated_input_and_conflicting_versions() -> None:
    assert len(prepare_documents([DOCUMENT, DOCUMENT])) == 1
    with pytest.raises(ValueError, match="immutable"):
        prepare_documents([DOCUMENT, DOCUMENT.replace("Synthetic metadata", "Changed metadata")])
    assert (
        len(prepare_documents([DOCUMENT, DOCUMENT.replace("version_no: 1", "version_no: 2")])) == 2
    )


@pytest.mark.parametrize(
    "source",
    [
        DOCUMENT + DOCUMENT,
        DOCUMENT.replace("version_no: 1", "version_no: true"),
        DOCUMENT.replace("version_no: 1", "version_no: 0"),
        DOCUMENT.replace("key: fixture_metadata", "key: INVALID"),
        DOCUMENT.replace("key: fixture_metadata", "key: fixture_metadata\nkey: duplicate"),
        DOCUMENT.replace("name: Synthetic metadata", "name: &x [a, b]\nextra: *x"),
        DOCUMENT.replace("name: Synthetic metadata", "name: !!python/object:os.system {}"),
        DOCUMENT.replace("name: Synthetic metadata", "name: Synthetic\nextra: .nan"),
        DOCUMENT.replace("name: Synthetic metadata", "name: Synthetic\nextra: 2026-01-01"),
        DOCUMENT + "```yaml strategy-spec\nkey: mismatch\nversion_no: 1\n```\n",
        "x" * 100001,
    ],
)
def test_invalid_staging_input_rejected(source: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        prepare_documents([DOCUMENT, source])


def test_embedded_spec_is_retained_but_never_run() -> None:
    # Opaque invalid DSL may be inspected, but has NOT passed G3; no evaluator here.
    source = DOCUMENT.replace(
        "name: Synthetic metadata",
        (
            'name: Synthetic metadata\nrules: [{expr: "__import__(unsafe)"}]'
            "\nvalidation: {methods: []}"
        ),
    )
    item = prepare_document(source)
    assert item is not None
    assert item.blocks["strategy-card"]["rules"] is not None
    assert item.runnable is False
    assert "G3" in item.gates_pending


def test_contract_serialization_without_fabricated_health() -> None:
    identifier = str(uuid.uuid4())
    summary = StrategySummary.model_validate(
        {
            "id": identifier,
            "key": "fixture_metadata",
            "name": "Synthetic metadata",
            "horizons": ["swing"],
            "risk_level": "normal",
            "current_version": {"id": identifier, "version_no": 1, "lifecycle": "draft"},
            "health": {"state": "observing", "weight": "1.0", "n": 0},
        }
    )
    serialized = json.loads(summary.model_dump_json())
    assert serialized["current_version"]["lifecycle"] == "draft"
    assert serialized["health"]["state"] == "observing"
    with pytest.raises(ValidationError):
        StrategySummary.model_validate(serialized | {"health": None})
    with pytest.raises(ValidationError):
        InternalCheck.model_validate(
            {
                "done": False,
                "method_types": [],
                "checked_on": None,
                "passed": True,
            }
        )
    detail = VersionDetail.model_validate(
        {
            "id": identifier,
            "strategy_id": identifier,
            "version_no": 1,
            "config": {},
            "lifecycle": "draft",
            "card_version_id": None,
            "risk_level": "normal",
            "param_hash": None,
            "parent_version_id": None,
            "internal_check": {"done": False, "method_types": [], "checked_on": None},
        }
    )
    assert VersionDetail.model_validate_json(detail.model_dump_json()) == detail
