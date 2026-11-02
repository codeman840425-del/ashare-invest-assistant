"""``/api/v1`` 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    admin,
    auth,
    data_licence,
    health,
    horizon,
    imports,
    me,
    meta,
    portfolio,
    trades,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(meta.router)
router.include_router(auth.router)
router.include_router(auth.register_router)
router.include_router(me.router)
router.include_router(data_licence.router)
router.include_router(admin.router)
router.include_router(accounts.router)
router.include_router(imports.router)
router.include_router(trades.router)
router.include_router(portfolio.router)
router.include_router(horizon.router)
