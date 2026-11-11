"""A18：完整静态资源先于参数资源选中，方法分派与 Allow 使用同一注册集合。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette._utils import get_route_path
from starlette.datastructures import URLPath
from starlette.exceptions import HTTPException
from starlette.routing import BaseRoute, Match, NoMatchFound
from starlette.types import Receive, Scope, Send


class StaticResourceRoute(BaseRoute):
    """保留已编译的 FastAPI 依赖与响应处理，只改变完整静态资源的选择顺序。"""

    def __init__(self, path: str, contexts: Sequence[RouteContext]) -> None:
        self.path = path
        self.path_format = path
        self.contexts = tuple(contexts)
        self.allowed_methods = sorted(
            {method for context in contexts for method in context.methods or ()}
        )

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and get_route_path(scope) == self.path:
            # 不支持的方法也选中此资源，不能继续落到动态参数路由。
            return Match.FULL, {}
        return Match.NONE, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope["aia.static_resource"] = self
        scope["route"] = self
        for context in self.contexts:
            if scope["method"] in (context.methods or ()):
                scope["route"] = context.original_route
                scope["endpoint"] = context.endpoint
                # iter_route_contexts 的 app 已包含有效前缀、依赖覆盖和 response_model。
                await context.app(scope, receive, send)
                return
        raise HTTPException(405, headers={"Allow": ", ".join(self.allowed_methods)})

    def url_path_for(self, name: str, /, **path_params: object) -> URLPath:
        # 保留原路由的命名 URL 解析，不注册额外 OpenAPI 方法。
        raise NoMatchFound(name, path_params)


def install_static_resources(app: FastAPI) -> None:
    resources: dict[str, list[RouteContext]] = defaultdict(list)
    for context in iter_route_contexts(app.router.routes):
        path = context.path
        if isinstance(context.original_route, APIRoute) and path and "{" not in path:
            resources[path].append(context)
    app.router.routes[:] = [
        *(StaticResourceRoute(path, contexts) for path, contexts in resources.items()),
        *(route for route in app.router.routes if not isinstance(route, StaticResourceRoute)),
    ]
