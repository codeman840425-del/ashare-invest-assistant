"""``/api/v1`` 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import admin, auth, data_licence, health, me, meta

router = APIRouter()
router.include_router(health.router)
router.include_router(meta.router)
router.include_router(auth.router)
router.include_router(auth.register_router)
router.include_router(me.router)
router.include_router(data_licence.router)
router.include_router(admin.router)
