"""同步 SQLAlchemy 引擎（psycopg 3）。

API 的认证类接口是同步 ``def`` 路由（FastAPI 放到线程池执行），用同步引擎即可，不引入 greenlet。
引擎按连接串缓存，进程内复用连接池。
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine


def _sqlalchemy_url(url: str) -> str:
    """``postgresql://`` / ``postgres://`` → ``postgresql+psycopg://``；已带驱动的原样返回。"""
    scheme, sep, rest = url.partition("://")
    if not sep or "+" in scheme:
        return url
    if scheme in {"postgresql", "postgres"}:
        return f"postgresql+psycopg://{rest}"
    return url


@lru_cache(maxsize=4)
def engine_for(url: str) -> Engine:
    return create_engine(_sqlalchemy_url(url), pool_pre_ping=True, pool_size=5, max_overflow=5)
