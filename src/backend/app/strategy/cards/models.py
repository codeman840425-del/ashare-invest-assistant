"""Contract-facing shapes only. No strategy content, feature declarations or gates fabricated."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.enums import (
    BarAdjust,
    CardRiskLevel,
    Dimension,
    EpistemicType,
    FeatureStatus,
    Horizon,
    Lifecycle,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeatureCatalogItem(ContractModel):
    feature_key: str
    description: str | None
    dimension: Dimension | None
    frequency: Literal["1m", "daily", "quarterly", "event"]
    adjust: BarAdjust
    unit: str
    warmup_bars: int | None = Field(strict=True, ge=0)
    available_at: JsonValue
    status: FeatureStatus
    epistemic_type: EpistemicType | None


class CurrentVersion(ContractModel):
    id: uuid.UUID
    version_no: int = Field(strict=True, ge=1)
    lifecycle: Lifecycle


class StrategyHealth(ContractModel):
    state: Literal["published", "observing"]
    weight: str
    n: int = Field(strict=True, ge=0)


class StrategySummary(ContractModel):
    id: uuid.UUID
    key: str
    name: str
    horizons: list[Horizon]
    risk_level: CardRiskLevel
    current_version: CurrentVersion
    health: StrategyHealth


class InternalCheck(ContractModel):
    # Public detail deliberately has no internal evaluation numbers/results.
    done: bool
    method_types: list[Literal["factor_ic", "event_study", "param_robustness"]]
    checked_on: dt.date | None


class VersionDetail(ContractModel):
    """Known C-section fields remain in config until full formal-card validation lands."""

    id: uuid.UUID
    strategy_id: uuid.UUID
    version_no: int = Field(strict=True, ge=1)
    config: dict[str, JsonValue]
    lifecycle: Lifecycle
    card_version_id: uuid.UUID | None
    risk_level: CardRiskLevel
    param_hash: str | None
    parent_version_id: uuid.UUID | None
    internal_check: InternalCheck


class CardIdentity(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    version_no: int = Field(strict=True, ge=1)
    name: str = Field(min_length=1, max_length=30)


class PendingImport(ContractModel):
    """Inspection result, NOT CARD_IMPORT_VALID or G1–G7 pass; never written to DB."""

    identity: CardIdentity
    source_hash: str
    narrative: str
    blocks: dict[str, dict[str, JsonValue]]
    status: Literal["awaiting_formal_cards"] = "awaiting_formal_cards"
    persistable: Literal[False] = False
    runnable: Literal[False] = False
    gates_pending: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
