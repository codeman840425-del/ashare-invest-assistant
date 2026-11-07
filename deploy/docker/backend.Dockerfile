# syntax=docker/dockerfile:1.7
# 后端镜像（T-O01a/T-O01b）：api、migrate（alembic）、worker/beat/ingest/signal-rt 共用同一镜像，只换启动命令。
#
# 构建上下文 = src/backend（只取 pyproject.toml、uv.lock、app/、alembic.ini、migrations/）。
# 上下文过滤：src/backend 下没有 .dockerignore（部署侧不改 src/），改用 BuildKit 的
#   "Dockerfile 同名 ignore 文件"：deploy/docker/backend.Dockerfile.dockerignore，
#   排除 probes/（含探针结果/样例）、.venv、__pycache__、.env 等，不会进入构建上下文。
# 手工构建：
#   docker build -f deploy/docker/backend.Dockerfile -t aia-backend:local src/backend
#
# 依赖：uv sync --frozen --no-dev 按 src/backend/uv.lock 精确安装（lock 与 pyproject 不一致即失败）。
# 代理：构建容器经 docker 网桥出网，本机透明代理直接可用（实测 pypi.org / files.pythonhosted.org 正常），
#   无需 HTTP(S)_PROXY；如在需显式代理的环境构建，用 --build-arg HTTP_PROXY=... HTTPS_PROXY=...（BuildKit 预定义参数，不会写进镜像）。

ARG PYTHON_IMAGE=python:3.13.18-slim-trixie@sha256:76baad6037690d6e8c4397fbcaef17bca6f19eecef822b708fe8fa3417d30bb5
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- builder
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app/src/backend
# 先只拷依赖清单，源码改动不会使依赖层失效
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY app ./app
# 迁移（T-O01b）：compose 的一次性 migrate 服务在镜像内执行 alembic upgrade head
COPY alembic.ini ./
COPY migrations ./migrations
RUN python -m compileall -q app migrations

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ARG APP_UID=10001
RUN groupadd --gid ${APP_UID} aia \
 && useradd --uid ${APP_UID} --gid aia --home-dir /app --no-create-home --shell /usr/sbin/nologin aia \
 && mkdir -p /app/config /var/lib/aia-dev/imports /var/lib/aia-dev/master \
 && chown aia:aia /var/lib/aia-dev/imports /var/lib/aia-dev/master \
 && chmod 700 /var/lib/aia-dev/imports /var/lib/aia-dev/master
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src/backend /app/src/backend
ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_DIR=/app/config
WORKDIR /app/src/backend
USER aia:aia
EXPOSE 8000
# 健康检查由 compose 定义（api 打 ${API_PREFIX}/health/live；worker 类用 app.workers.healthcheck）；--proxy-headers 信任 nginx 传来的 X-Forwarded-*
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
