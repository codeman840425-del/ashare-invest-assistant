"""``GET /horizon-assessments?security_code=`` 🔒（契约 v0.2.8 §4 / §5.1；T-B30 / T-B47）。

分类器 1.2.0（``config/horizon_classifier.yaml`` version_no 3）。目前按请求即时求值
（重算触发器与 ``symbol_horizon_assessments`` 落库待重算任务；见 app.strategy.horizon.inputs）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.v1.trades import normalize_code
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.strategy.horizon import classifier
from app.strategy.horizon import inputs as hz_inputs

router = APIRouter()


@router.get("/horizon-assessments")
def get_horizon_assessment(
    auth: AuthDep,
    settings: SettingsDep,
    engine: EngineDep,
    security_code: Annotated[str, Query(min_length=1, max_length=16)],
) -> dict[str, Any]:
    cfg = settings.business.horizon_classifier
    with engine.connect() as conn:
        code = normalize_code(conn, security_code)
        got = hz_inputs.collect(conn, auth.user_id, code, list(cfg.features))
    res = classifier.classify(cfg, got.values)
    used = {r.input for r in res.reasons if r.input is not None}
    evidence, ids = hz_inputs.evidence(got, used)
    return {
        "security_code": code,
        "suitable": res.suitable,
        "scores": res.scores,
        "reasons": [
            {
                "horizon": r.horizon,
                "polarity": r.polarity,
                "text": r.text,
                "expr": None,
                "evidence_ids": [ids[r.input]] if r.input in ids else [],
            }
            for r in res.reasons
        ],
        "inputs_missing": res.inputs_missing,
        "caps": res.caps,
        "hints": res.hints,
        "classifier_version": res.classifier_version,
        "snapshot_id": hz_inputs.snapshot_id(res.classifier_version, code, got.values),
        "evidence": evidence,
    }
