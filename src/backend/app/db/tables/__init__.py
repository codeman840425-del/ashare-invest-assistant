"""导入全部表定义，使 :data:`app.db.base.metadata` 完整。

Alembic env 与 ``alembic check`` 依赖本包。
"""

from __future__ import annotations

from app.db.tables import (
    accounts,
    evaluation,
    ingest_gate,
    licences,
    llm,
    market,
    membership,
    notify,
    ops,
    realtime,
    research,
    reviews,
    signals,
    strategy,
    users,
    vendor,
)

__all__ = [
    "accounts",
    "evaluation",
    "ingest_gate",
    "licences",
    "llm",
    "market",
    "membership",
    "notify",
    "ops",
    "realtime",
    "research",
    "reviews",
    "signals",
    "strategy",
    "users",
    "vendor",
]
