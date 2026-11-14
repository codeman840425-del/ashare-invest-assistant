"""先选具体资源再判方法；实际分派与 Allow 使用同一注册集合。"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette.datastructures import URLPath
from starlette.exceptions import HTTPException
from starlette.routing import BaseRoute, Match, NoMatchFound
from starlette.types import Receive, Scope, Send

_PARAMETER = re.compile(r"\{[^{}]+\}")


def _specificity(path: str) -> tuple[int, int]:
    """更多字面段优先；同级保留注册顺序，参数名字不影响优先级。"""
    segments = path.strip("/").split("/")
    return (
        sum(bool(segment) and "{" not in segment for segment in segments),
        len(_PARAMETER.sub("", path)),
    )


class ResourceRoute(BaseRoute):
    """保留 FastAPI 有效前缀、参数转换、依赖覆盖及响应模型。"""

    def __init__(self, path: str, contexts: Sequence[RouteContext]) -> None:
        self.path = path
        self.path_format = path
        self.contexts = tuple(contexts)
        self.allowed_methods = sorted(
            {method for context in contexts for method in context.methods or ()}
        )

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] != "http":
            return Match.NONE, {}
        match, child_scope = self.contexts[0].matches(scope)
        if match != Match.NONE:
            # PARTIAL 也选中该具体资源，不能继续被较宽泛的参数路由吞并。
            return Match.FULL, child_scope
        return Match.NONE, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope["aia.resource"] = self
        scope["route"] = self
        for context in self.contexts:
            match, child_scope = context.matches(scope)
            if match == Match.FULL:
                # 使用实际注册方法对应的匹配结果，保留 UUID converter 和 path_params。
                scope.update(child_scope)
                scope["route"] = context.original_route
                scope["endpoint"] = context.endpoint
                await context.app(scope, receive, send)
                return
        raise HTTPException(405, headers={"Allow": ", ".join(self.allowed_methods)})

    def url_path_for(self, name: str, /, **path_params: object) -> URLPath:
        # 原路由继续处理命名 URL，资源选择器不注册额外 OpenAPI 方法。
        raise NoMatchFound(name, path_params)


class StaticResourceRoute(ResourceRoute):
    """完整静态资源的兼容名称；与含参数资源使用同一分派实现。"""


def install_resources(app: FastAPI) -> None:
    resources: dict[str, list[RouteContext]] = defaultdict(list)
    for context in iter_route_contexts(app.router.routes):
        path = context.path
        if isinstance(context.original_route, APIRoute) and path:
            resources[path].append(context)
    ordered = sorted(resources, key=_specificity, reverse=True)
    app.router.routes[:] = [
        *(
            (ResourceRoute if "{" in path else StaticResourceRoute)(path, resources[path])
            for path in ordered
        ),
        *(route for route in app.router.routes if not isinstance(route, ResourceRoute)),
    ]


def install_static_resources(app: FastAPI) -> None:
    """保留7908新增pool的调用入口，不改已有测试。"""
    install_resources(app)
