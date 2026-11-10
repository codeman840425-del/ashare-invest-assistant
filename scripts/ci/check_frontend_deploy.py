#!/usr/bin/env python3
"""T-O19：前端 dist 接入网关。静态检查，不连麦蕊、不读密钥。

确认 / 不再是占位页，SPA 深链回退 index.html，/assets/ 缺失为 404，
/api 仍反代且不会落到 index.html，健康检查与 dns 不变，
构建文件不携带运行时密钥，worker 的 master 卷还在。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

NGINX_PIN = "nginx:1.31.2-alpine3.23@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa"
PLACEHOLDER = "frontend not built yet"
FORBIDDEN_BUILD = ("MAIRUI_", "APP_MASTER_KEY", "PASSWORD", "SECRET")


MASTER_VOL = "master:${MASTER_SNAPSHOT_PATH:-/var/lib/aia-dev/master}"


def _block(conf: str, start: str, until: str | None = None) -> str:
    i = conf.find(start)
    if i < 0:
        return ""
    j = conf.find(until, i + len(start)) if until else -1
    return conf[i:] if j < 0 else conf[i:j]


def _service_block(yml: str, name: str) -> str:
    """顶层服务块（两个空格缩进的键），不含下一个同级键。"""
    start = f"\n  {name}:\n"
    i = yml.find(start)
    if i < 0:
        return ""
    rest = yml[i + len(start):]
    nxt = re.search(r"\n  [A-Za-z0-9._-]+:", rest)
    return rest[: nxt.start()] if nxt else rest


def _service_volumes(block: str) -> list[str]:
    """从服务块里取出 volumes 列表项（短语法），忽略注释。不在整份文件里搜字符串。"""
    items: list[str] = []
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        if re.match(r"^    volumes:\s*$", lines[i]):
            i += 1
            while i < len(lines):
                ln = lines[i]
                if ln.startswith("      - "):
                    items.append(ln[len("      - "):].strip())
                elif ln.startswith("      #") or not ln.strip():
                    pass
                else:
                    break
                i += 1
            break
        i += 1
    return items


def check(repo: Path) -> list[str]:
    errs: list[str] = []
    nginx = repo / "deploy/nginx/nginx.conf"
    compose = repo / "deploy/compose/docker-compose.yml"
    dockerf = repo / "deploy/docker/frontend.Dockerfile"
    for p in (nginx, compose, dockerf):
        if not p.is_file():
            errs.append(f"缺少 {p.relative_to(repo)}")
    if errs:
        return errs
    conf = nginx.read_text(encoding="utf-8")
    yml = compose.read_text(encoding="utf-8")
    df = dockerf.read_text(encoding="utf-8")

    if PLACEHOLDER in conf:
        errs.append("nginx.conf 仍返回前端占位页")
    if "include /etc/nginx/mime.types;" not in conf:
        errs.append("nginx.conf 没有 include mime.types（静态资源会没有正确的 Content-Type）")
    assets = _block(conf, "location /assets/ {", "location / {")
    if "try_files $uri =404;" not in assets or "try_files $uri /index.html" in assets:
        errs.append("location /assets/ 必须 try_files $uri =404，且不能回退 index.html")
    if "error_page 404 @assets_missing;" not in assets:
        errs.append("location /assets/ 必须用 error_page 404 @assets_missing，不能回 nginx 默认错误页")
    missing = _block(conf, "location @assets_missing {", "location / {")
    missing_code = "\n".join(line.split("#", 1)[0] for line in missing.splitlines())
    if 'return 404 "not found\\n";' not in missing_code:
        errs.append("缺失静态资源必须 return 404 固定短正文，不能用空 return（会落回内置 HTML 页）")
    if "<html" in missing_code.lower() or "nginx" in missing_code.lower():
        errs.append("缺失静态资源的 404 正文不得含 nginx 或 HTML")
    if 'add_header Cache-Control "no-store" always;' not in missing_code:
        errs.append("缺失 /assets/ 必须 Cache-Control: no-store，不能长期缓存")
    if "31536000" in missing_code or "immutable" in missing_code:
        errs.append("缺失 /assets/ 的 404 不得使用一年 immutable 缓存")
    assets_ok = _block(conf, "location /assets/ {", "location @assets_missing {")
    if 'add_header Cache-Control "public, max-age=31536000, immutable" always;' not in assets_ok:
        errs.append("已有 /assets/ 资源必须仍是一年 immutable 缓存")
    spa = _block(conf, "location / {", "\n  }\n")
    if "try_files $uri /index.html;" not in spa:
        errs.append("location / 必须 try_files $uri /index.html（SPA 深链）")
    code = "\n".join(line.split("#", 1)[0] for line in conf.splitlines())
    server_at = code.find("server {")
    assets_at = code.find("location /assets/ {", server_at if server_at >= 0 else 0)
    root_at = code.find("root /usr/share/nginx/html;", server_at if server_at >= 0 else 0)
    if server_at < 0 or assets_at < 0 or not (server_at < root_at < assets_at):
        errs.append(
            "server 必须在 location /assets/ 之前写 root /usr/share/nginx/html;"
            "（本文件替换镜像 nginx.conf 且不 include conf.d；缺 root 时 try_files 回退 /index.html 会内部重定向循环）"
        )
    if "root " in "\n".join(line.split("#", 1)[0] for line in assets.splitlines()):
        errs.append("location /assets/ 不得另行指定 root")
    if "root " in "\n".join(line.split("#", 1)[0] for line in spa.splitlines()):
        errs.append("location / 不得另行指定 root")
    if "return 200" in spa:
        errs.append("location / 不应再直接 return 200")
    api = _block(conf, "location /api/ {", "location ~")
    if "proxy_pass http://$aia_api_upstream;" not in api:
        errs.append("location /api/ 必须继续 proxy_pass http://$aia_api_upstream（不带 URI）")
    if "try_files" in api or "index.html" in api:
        errs.append("location /api/ 不得回退到前端页面")
    if "location = /healthz" not in conf or 'return 200 "ok\\n"' not in conf:
        errs.append("location = /healthz 必须仍由 nginx 自答")
    if "location = /health/live" not in conf or "/api/v1/health/live$is_args$args" not in conf:
        errs.append("location = /health/live 必须仍反代后端存活检查")
    if "limit_req zone=aia_api" not in api or "limit_req zone=aia_search" not in conf:
        errs.append("既有限流指令被删掉了")

    if "image: ${AIA_FRONTEND_IMAGE:-aia-frontend:local}" not in yml:
        errs.append("compose nginx 未使用 AIA_FRONTEND_IMAGE")
    if "context: ../../src/frontend" not in yml or "dockerfile: ../../deploy/docker/frontend.Dockerfile" not in yml:
        errs.append("compose nginx 的构建上下文必须是 src/frontend，Dockerfile 在 deploy/docker")
    if "network_mode:" in yml.split("nginx:", 1)[-1].split("\n  api:", 1)[0]:
        errs.append("nginx 不得使用 host 网络")
    ngx = yml.split("nginx:", 1)[-1].split("\n  api:", 1)[0]
    if "secrets:" in ngx:
        errs.append("nginx 不得挂 secret")
    if "../nginx/nginx.conf:/etc/nginx/nginx.conf:ro" not in ngx or "../nginx/limits.conf:/etc/nginx/aia-limits.conf:ro" not in ngx:
        errs.append("nginx 仍须只读挂载 nginx.conf 与 limits.conf")
    if "dns:\n      - 127.0.0.1" not in ngx or "/health/live" not in ngx:
        errs.append("nginx 的 dns 127.0.0.1 或 /health/live 健康检查丢了")
    # 按服务 volumes 列表检查，不能在整份 yml 里搜字符串。
    # T-O67/L-5 起 master-bootstrap 也挂同一 master 卷，须单独核对。
    worker = _service_block(yml, "worker")
    if not worker:
        errs.append("compose 没有 worker 服务")
    else:
        if MASTER_VOL not in _service_volumes(worker):
            errs.append("worker 的 master 快照卷丢了（T-O18）")
        if "MASTER_SNAPSHOT_PATH:" not in worker:
            errs.append("worker 的 MASTER_SNAPSHOT_PATH 丢了（T-O18）")
    boot = _service_block(yml, "master-bootstrap")
    if boot:
        if MASTER_VOL not in _service_volumes(boot):
            errs.append("master-bootstrap 的 master 快照卷丢了")
        if "MASTER_SNAPSHOT_PATH:" not in boot:
            errs.append("master-bootstrap 的 MASTER_SNAPSHOT_PATH 丢了")

    if f"FROM {NGINX_PIN}" not in df:
        errs.append("frontend.Dockerfile 最终阶段必须 FROM 原来的 nginx digest")
    if "pnpm install --frozen-lockfile" not in df or "pnpm run build" not in df:
        errs.append("前端构建必须 pnpm install --frozen-lockfile 且 pnpm run build")
    if "COPY --from=build /src/dist /usr/share/nginx/html" not in df:
        errs.append("构建结果必须复制到 /usr/share/nginx/html")
    if "COPY . " in df or "COPY .env" in df:
        errs.append("Dockerfile 不得整目录 COPY，也不得复制 .env")
    for needle in FORBIDDEN_BUILD:
        if needle in df:
            errs.append(f"frontend.Dockerfile 含有 {needle}（构建不得带运行时密钥或麦蕊变量）")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)
    errs = check(args.repo.resolve())
    for e in errs:
        print(f"::error title=frontend-deploy::{e}")
    print(f"check_frontend_deploy: {len(errs)} 个问题")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
