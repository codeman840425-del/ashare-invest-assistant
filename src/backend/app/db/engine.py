"""同步 SQLAlchemy 引擎（psycopg 3）。

API 的认证类接口是同步 ``def`` 路由（FastAPI 放到线程池执行），用同步引擎即可，不引入 greenlet。
引擎按连接串缓存，进程内复用连接池。

T-A87 L-1：``profile="ingest"`` 使用 NullPool，并设 connect_timeout=3 与语句/锁超时。
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool


def _sqlalchemy_url(url: str) -> str:
    """``postgresql://`` / ``postgres://`` → ``postgresql+psycopg://``；已带驱动的原样返回。"""
    scheme, sep, rest = url.partition("://")
    if not sep or "+" in scheme:
        return url
    if scheme in {"postgresql", "postgres"}:
        return f"postgresql+psycopg://{rest}"
    return url


@lru_cache(maxsize=8)
def engine_for(url: str, profile: str = "default") -> Engine:
    sa_url = _sqlalchemy_url(url)
    if profile == "ingest":
        return create_engine(
            sa_url,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 3,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
                "tcp_user_timeout": 5000,
                "options": "-c statement_timeout=5000 -c lock_timeout=2000",
            },
        )
    return create_engine(sa_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
