"""``/api/v1`` 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    admin,
    aggregates,
    auth,
    candidate_signals,
    candidates,
    daily_reports,
    data_licence,
    health,
    horizon,
    imports,
    instances,
    me,
    meta,
    notifications,
    portfolio,
    promotions,
    risk_controls,
    securities,
    security_financials,
    signal_events,
    strategy_cards,
    suggestions,
    trades,
    watchlist,
)
from app.plans.api import router as plans_router
from app.plans.drafts import router as drafts_router
from app.tracking.api import router as tracking_router

router = APIRouter()
router.include_router(notifications.router)
router.include_router(health.router)
router.include_router(meta.router)
router.include_router(auth.router)
router.include_router(auth.register_router)
router.include_router(auth.login_router)
router.include_router(me.router)
router.include_router(data_licence.router)
router.include_router(admin.router)
router.include_router(accounts.router)
router.include_router(imports.router)
router.include_router(trades.router)
router.include_router(watchlist.router)
router.include_router(portfolio.router)
router.include_router(horizon.router)
router.include_router(candidates.router)

router.include_router(instances.router)

router.include_router(aggregates.router)
router.include_router(securities.router)
router.include_router(security_financials.router)

router.include_router(strategy_cards.router)

router.include_router(candidate_signals.router)

router.include_router(suggestions.router)


router.include_router(daily_reports.router)

router.include_router(promotions.router)
router.include_router(risk_controls.router)

router.include_router(tracking_router)
router.include_router(plans_router)
router.include_router(drafts_router)


router.include_router(signal_events.router)
