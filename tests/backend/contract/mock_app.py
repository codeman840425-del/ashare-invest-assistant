"""契约脚手架用的本地 WSGI 桩（T-T01）：按 openapi_v1_stub.json 返回固定响应。纯标准库，不联网。

`make_app(health_status="ok")`；传入非法值（如 "bad"）可构造"违约"的服务，用来证明契约测试能抓到问题。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

STUB = json.loads((Path(__file__).with_name("openapi_v1_stub.json")).read_text(encoding="utf-8"))

StartResponse = Callable[..., Any]
KNOWN_PATHS = {"/api/v1" + p for p in STUB["paths"]}


def make_app(health_status: str = "ok") -> Callable[[dict, StartResponse], Iterable[bytes]]:
    def app(environ: dict, start_response: StartResponse) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        rid = environ.get("HTTP_X_REQUEST_ID") or f"req_{uuid.uuid4().hex[:8]}"

        def send(status: str, body: Any, extra: list[tuple[str, str]] | None = None) -> Iterable[bytes]:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            start_response(
                status,
                [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(data))),
                    ("X-Request-Id", rid),
                    *(extra or []),
                ],
            )
            return [data]

        if method == "GET" and path == "/openapi.json":
            return send("200 OK", STUB)
        if method == "GET" and path == "/api/v1/health":
            return send("200 OK", {"status": health_status, "db": "ok", "redis": "ok", "ingest": "ok"})
        if method == "GET" and path == "/api/v1/me":
            return send(
                "401 Unauthorized",
                {"error": {"code": "AUTH_REQUIRED", "message": "请先登录", "details": None, "request_id": rid}},
            )
        if path in KNOWN_PATHS:
            # 路径存在但方法未声明 → 405（schemathesis ST204；FastAPI 默认行为一致）
            return send(
                "405 Method Not Allowed",
                {"error": {"code": "METHOD_NOT_ALLOWED", "message": "方法不允许", "details": None, "request_id": rid}},
                [("Allow", "GET")],
            )
        return send(
            "404 Not Found",
            {"error": {"code": "NOT_FOUND", "message": "不存在", "details": None, "request_id": rid}},
        )

    return app
