# T-O01a 报告：api 换真实应用 + 后端 Dockerfile + nginx 保留 /api 前缀

- 仓库：/workspace/ashare-invest-assistant
- 开工时确认的 HEAD：`7209877`（T-O08）。任务进行中，别人又在本地提交了 `f34fcfd`（fix(backend): T-B01 评审 M1–M8，13:10 MST）和 `2bc6322`（docs，13:12 MST）。
- **实际提交基于 HEAD `2bc6322`。** 最终验收也是在 2bc6322 的新克隆上重跑的，含后端的严格 config 校验。
- **本次提交：`96c1c8e3ee3fa62e4cd7df4a45dfd4944d7941b7`**，只在本地，没有 push、reset 或 rebase。

## 1. 改动的文件（只有 deploy/，共 7 个文件，+118/−10）

| 文件 | 改动 |
|---|---|
| deploy/nginx/nginx.conf | proxy_pass 去掉末尾斜杠；加上 HTTP/1.1 keep-alive 到上游 |
| deploy/docker/backend.Dockerfile | 新建：多阶段构建，用 uv，以非 root 用户运行 |
| deploy/docker/backend.Dockerfile.dockerignore | 新建：BuildKit 的同名 ignore 文件，作用于上下文 src/backend |
| deploy/compose/docker-compose.yml | api 改为真实镜像、命令和健康检查；新增环境变量；api 挂载 config/ |
| deploy/compose/docker-compose.dev.yml | api 用 `--reload` 热重载 |
| deploy/env/.env.example | 新增 LOG_LEVEL、API_PREFIX、HEALTH_CHECK_TIMEOUT_S、AIA_BACKEND_IMAGE |
| deploy/scripts/up.sh | 默认 `up --build`（设 `AIA_UP_BUILD=0` 可跳过） |

src/、tests/、docs/ 和根目录都没有动。别人未提交的改动（src/backend 的 pyproject/uv.lock、src/frontend、docs/strategies、.github/ 等）都没有暂存。

## 2. nginx 改动前后

```diff
     location /api/ {
-      proxy_pass <url>
+      proxy_pass <url>
+      proxy_http_version 1.1;
+      proxy_set_header Connection "";
       proxy_set_header Host $host;
       proxy_set_header X-Request-Id $request_id;
```

- **原因：** proxy_pass 带了 URI（`/`）时，nginx 会把匹配到的 `/api/` 换成 `/`，后端收到的是 `/v1/health`，所以返回 404。不带 URI 时请求路径原样转发。
- **路由前缀核对：** `src/backend/app/main.py` 里是 `app.include_router(v1_router, prefix=cfg.api_prefix)`，`api_prefix` 默认值是 `/api/v1`，两者一致。
- **/healthz：** 仍由 nginx 自己 `return 200`，不依赖上游。验收时返回 200，body 为 `ok`。
- **注意：** 如果以后改了 API_PREFIX，前缀不在 `/api/` 下面，就要同步改 nginx 的 location。

## 3. Dockerfile 要点（deploy/docker/backend.Dockerfile）

**镜像和版本固定**
- 基础镜像：`python:3.13.18-slim-trixie<at>sha256:76baad60…0bb5`，与 compose 占位镜像是同一个 digest。
- uv：`ghcr.io/astral-sh/uv:0.13.6<at>sha256:af22a52f…86d0`（多架构 index digest，2026-11-01 时的最新版）。
- 两者都通过 `ARG PYTHON_IMAGE` / `ARG UV_IMAGE` 可覆盖。

**builder 阶段**
- 先只 COPY `pyproject.toml` 和 `uv.lock`，再执行 `uv sync --frozen --no-dev --no-install-project`。
  - 带 BuildKit cache mount。
  - `UV_PYTHON_DOWNLOADS=never`，只用镜像自带的 Python。
  - venv 在 `/opt/venv`，开了 `UV_COMPILE_BYTECODE`。
- 然后 COPY `app/`，再 compileall。
- 后端是 `package=false`，所以不安装项目本身。

**runtime 阶段**
- 同一个基础镜像，只复制 `/opt/venv` 和 `/app/src/backend`（里面只有 pyproject、uv.lock 和 app）。不含 uv、构建缓存或 dev 依赖。
- 运行用户 `aia`，uid/gid 10001。验收时 `id` 输出 `uid=10001(aia) gid=10001(aia)`。
- `/var/lib/aia-dev/imports` 预先 chown 给 aia，named volume 首次挂载时继承这个属主，实测可写。
- `WORKDIR /app/src/backend`，`PATH=/opt/venv/bin:$PATH`，`CONFIG_DIR=/app/config`。
- 默认 CMD：`uvicorn app.main:app --host <host> --port 8000 --proxy-headers --forwarded-allow-ips *`。

**上下文和 dockerignore**
- src/backend 下没有 .dockerignore，而部署侧不能改 src/。
- 解决办法：用 BuildKit 支持的 `<Dockerfile 名>.dockerignore`，放在 Dockerfile 旁边，也就是 `deploy/docker/backend.Dockerfile.dockerignore`。
  - 采用白名单：只放行 `pyproject.toml`、`uv.lock` 和 `app/`；排除 `__pycache__`、`*.pyc`、`.env*`。
- 实测：在上下文里放一个假的 `probes/results/x`，再用全量 COPY 的探针 Dockerfile 检查，结果上下文里只有 app/、pyproject.toml、uv.lock。探针结果、.venv 等都不会被发给构建器。
- compose 和手工构建都会自动生效，需要 BuildKit（Docker 23+ 默认就是）：
  - compose：`build.context: ../../src/backend`，`dockerfile: ../../deploy/docker/backend.Dockerfile`。
  - 手工：`docker build -f deploy/docker/backend.Dockerfile -t aia-backend:local src/backend`。
- 不需要 dockerfile_inline，也不需要额外的构建脚本。

**代理**
- pip/uv 走代理**没有问题**。
  - 本机是透明代理，构建容器经 docker 网桥出网，直接就能访问 pypi.org 和 files.pythonhosted.org。
  - 用 `--no-cache` 的 uv 冷下载 24 个包也正常。
  - ghcr.io 拉 uv 镜像正常。
  - 不需要设置 HTTP(S)_PROXY。
- 如果以后换到需要显式代理的环境，用 `--build-arg HTTP_PROXY=… HTTPS_PROXY=…`。这是 BuildKit 预定义参数，不会写进镜像。Dockerfile 注释里已经写明。
- 冷构建约 6 秒，有缓存时 1–2 秒。

## 4. 新增的环境变量

依据后端 `app/config.py`（pydantic-settings，只读环境变量，大小写不敏感，不读 .env）。

| 变量 | 注入到 | 默认值 | 说明 |
|---|---|---|---|
| LOG_LEVEL | 所有应用服务（x-app-env） | INFO | 后端 Settings.log_level |
| CONFIG_DIR | 所有应用服务（x-app-env） | /app/config（固定） | 仓库 `config/` 以只读方式挂到这里。**base 文件里也挂了**（live 模式必须有，见第 7 节） |
| API_PREFIX | api | /api/v1 | 健康检查 URL 也读这个变量 |
| HEALTH_CHECK_TIMEOUT_S | api | 1.0 | /health 探测 PG/Redis 时每项的超时 |
| AIA_BACKEND_IMAGE | 只用于 compose 插值 | aia-backend:local | 构建出的镜像 tag |

已有、沿用的变量：
- APP_ENV、SERVICE_NAME、APP_MASTER_KEY（必填；非 local/test 环境下至少 32 字符，示例占位串是 38 字符）。
- DATABASE_URL（compose 拼成 `postgresql+psycop<path>`，后端可以接受）。
- REDIS_URL、TZ（镜像里有 tzdata，实测是 CST）。

有意**没有**放进 compose 的后端变量：INGEST_HEARTBEAT_KEY / INGEST_PAUSED_KEY / INGEST_STALE_AFTER_S / PAGE_LIMIT_* / CURSOR_TTL_S。
- 现在的后端会从 `config/*.yaml` 取值，环境变量只是覆盖。
- 如果 compose 给了默认值，就会把 yaml 盖掉。所以这些变量保持未设置，需要时再按需加。

MAIRUI_*：仍然**只在 ingest** 的 environment 里。不用 env_file。dev 叠加文件会把 MAIRUI_LICENCE 强制置空。

## 5. compose 中的 api

- base 文件：
  - `image: ${AIA_BACKEND_IMAGE:-aia-backend:local}` 加 `build`（见上节）。
  - command 为 uvicorn（不带 reload）。
  - 卷：imports 和 `../../confi<path>`。
- 健康检查：`python -c urllib` 请求 `<url>`，interval 10s，start_period 15s。
  - 后端的 /health 永远返回 200，依赖异常只体现在 body 的 `status=degraded` 里，所以这个检查只判断存活。
- dev 叠加文件：
  - 源码 `../../src/backen<path>` 会覆盖镜像里的代码；依赖在 /opt/venv，不受影响。
  - command 追加 `--reload --reload-dir /app/src/backend/app`，配合已有的 `WATCHFILES_FORCE_POLLING=true` 用轮询方式监视。
- worker、beat、ingest、signal-rt：后端还没有入口，**保持占位**。
  - compose 里预留了 `*backend-image` / `*backend-build` 锚点，入口落地后只需换 command 和 healthcheck。
- nginx 仍然依赖 api 达到 service_healthy。

## 6. 验收结果

做法：从本地仓库全新克隆到 `/tmp/aia-o01a-accept`（基于 HEAD 2bc6322），套上本次暂存的 diff。
- 项目名 `COMPOSE_PROJECT_NAME=aia-accept-o01a`。
- 端口用 nginx 18080、PG 15432、Redis 16379，避免和默认的 aia 冲突。
- 全程用 `env -u MAIRUI_LICENCE` 运行。
- 开工时在 7209877 上已经完整跑过一轮。别人的提交进来后，又在 2bc6322 上重跑了一轮，结论相同。

**dev 模式（默认叠加 dev 文件），`deploy/scripts/up.sh`**
- 镜像 `aia-backend:local` 构建成功，8/8 容器 healthy，`up --wait` 约 20 秒返回。
- `curl <url>` → **200**，body：
  `{"status":"degraded","db":"ok","redis":"ok","ingest":"stale","checked_at":"2026-11-02T04:12:40+08:00","version":"0.1.0"}`
  - degraded 是预期结果：ingest 还是占位，没有心跳，所以 ingest 判定为 stale。db 和 redis 都是 ok。
- `/healthz` → **200**，body `ok`。
- `/api/v1/health/live` → 200，body `{"status":"ok"}`。
- `/api/v1/health/ready` → 200，内容同 /health。
- 不存在的路径 `/api/v1/nonexistent` → 404，返回后端统一的错误 JSON，request_id 与 nginx 的 `$request_id` 一致。
- 修复前那种去前缀后的路径（`/v1/health`）现在落到 nginx 的 `location /` 占位页，说明 /api 前缀已经原样转发。
- 后端启动日志：`app created env=local prefix=/api/v1 business_config=['realtime','ingest','market_rules','risk_controls','horizon_classifier']`。5 个 config 文件都通过了严格校验。
- 热重载：
  - 日志里有 `Will watch for changes in these directories: ['/app/src/backend/app']`。
  - `touch app/main.py` 后出现 `WatchFiles detected changes … Reloading...`，然后是 `Application startup complete`，之后 /health 仍返回 200。
- api 容器的情况：
  - cmd 带 `--reload`，user 为 `aia:aia`。
  - 挂载：`/app/config` 只读、`/app/src/backend` 只读、imports 可读写。
  - PG 只暴露在 <host>:15432。

**live 模式（只用 base 文件，`AIA_PROFILE=live`，克隆的 .env 里写了假 licence `FAKE-O01A-NOT-A-REAL-LICENCE`）**
- 8/8 healthy。`/api/v1/health` → 200，body 同上（degraded，db/redis 都是 ok）。`/healthz` → 200。
- api 的 cmd 不带 `--reload`，没有源码挂载，只有 `/app/config` 只读和 imports。PG 和 Redis 没有发布到宿主机端口。
- 用 `docker compose config` 确认，MAIRUI_LICENCE 只出现在 ingest 下面。

**docker inspect 检查 MAIRUI_LICENCE（遍历全部 8 个容器的 .Config.Env）**

| 模式 | ingest | api / worker / beat / signal-rt / nginx / postgres / redis |
|---|---|---|
| dev | 有这个变量，值为空（长度 0，被 dev 叠加文件置空） | 都没有 |
| live（假 licence） | 有，值为假 licence（长度 28），MAIRUI_MODE=replay | 都没有 |

**清理**
- 执行了 `down.sh -v`：容器、3 个卷（pgdata、redisdata、imports）和网络都已删除。
- 克隆目录 `/tmp/aia-o01a-accept` 已删除。
- 自己构建的镜像都已删除：aia-backend:local / :bt / :wt-probe，以及临时拉的 uv:latest 和 uv python 镜像。
- 复查结果为 0 个容器、0 个卷、0 个网络、0 个 aia-backend 镜像。
- BuildKit 构建缓存保留，这样下次构建更快。
- 没有碰 aia 主项目的库和容器（本次开工时没有在运行的容器）。`/tmp/aia-scan` 和 `/tmp/aia-v02` 是别人的，没有动。
- 全程没有调用麦蕊接口，ingest 是占位。没有读取或使用 shell 里的真实 licence。

**额外做的兼容性探测（只读，不提交）**
- 当时 f34fcfd 还没提交。我用主仓库工作区的 src/backend 构建了一次，挂上 config/ 后 /health、/health/live、/health/ready 都返回 200。
  - 这次构建包含别人未提交的 pyproject/uv.lock 改动（新增 sqlalchemy 和 alembic），说明 `uv sync --frozen` 对这份 lock 也能正常构建。
- **不挂 config/ 时，`import app.main` 直接报 `ConfigError: … 缺少 ['horizon_classifier', … 'risk_controls']`。** 所以 base 文件里必须挂载 config/。

## 7. 扫描结果

- **rg**，扫描范围是暂存 diff 的新增行：
  - 规则覆盖私钥/证书头、10 位<account-field>模式、`[AB]\d{9}`、“<account-field>”/shareholder、licence/password 赋值、ghp/xox/sk token。
  - 结果：**0 命中**。
  - 暂存的文件里没有 `.env`、`*.pem/key/crt/p12/pfx`、`*.dump`。
  - `deploy/env/.env` 被 `.gitignore` 的 `*.env` 规则忽略。
  - 暂存区里没有 deploy/ 以外的文件。
- **gitleaks v8.30.1**（zricethezav/gitleaks:latest）：
  - `git --staged`：no leaks found。
  - `dir deploy/`（含本地被忽略的 .env）：no leaks found。
  - `git` 全部历史（提交前 9 个提交）：1 条 generic-api-key，位于 `docs/plan.md:1257`，提交 ccf7cba（Phase 0）。
    - 这是表结构文档里的示例 `key:"<REDACTED-EXAMPLE>"`，**误报**。不是本次引入的，也不在 deploy/ 里。

## 8. 遗留问题

1. **up.sh 默认会构建。** 每次 `up` 都会跑一次 buildx，有缓存时 1–2 秒。离线环境或想用现成镜像时，设 `AIA_UP_BUILD=0`。
2. **dev 模式下依赖变化需要重建镜像。** 改了 pyproject/uv.lock 后，挂载进来的源码会用到新依赖，但镜像里还没有，需要重新 `up`（默认会 build）。热重载只覆盖 `app/` 的代码改动。
3. **`/health` 永远返回 200。** compose 和 nginx 的健康检查只能判断存活，判断不了就绪。
   - 现在后端已经有 `/health/live` 和 `/health/ready`。等契约确定后，可以把 compose 的检查换成 `/health/live`，就绪状态另外监控 `/health/ready` body 里的 status。
   - 本次按任务要求打的是 `/api/v1/health`。
4. **nginx 会覆盖客户端传来的 X-Request-Id**（`proxy_set_header X-Request-Id $request_id`）。如果需要透传客户端的 ID，以后改成 `$http_x_request_id` 优先。
5. **worker、beat、ingest、signal-rt 仍是占位镜像。** 它们也拿到了 LOG_LEVEL 和 CONFIG_DIR 两个变量，这两个变量无害，但没有用上。
6. **代码在镜像内的路径是 `/app/src/backend`**，与 T-B01 约定和 dev 挂载点一致。后端如果依赖 `parents[3]` 这种仓库相对路径推导，在镜像里会落到 `/`。目前因为显式设置了 CONFIG_DIR，没有问题。

## 9. 需要后端配合的事项

1. **src/backend/.dockerignore（可选）。** 现在靠 deploy 侧的 `backend.Dockerfile.dockerignore` 白名单。如果后端以后在 `app/` 之外加了运行时需要的文件（比如 alembic.ini、migrations/），需要通知部署侧，把它加进白名单和 COPY。
2. **config/ 是启动的硬依赖。** 严格校验要求正好 5 个 yaml，缺一个就无法 import。新增或删减 config 文件时要同步通知部署侧（compose 是整目录挂载，一般不用改，但 live 主机上也必须有这个目录）。
3. **健康检查路径。** 请确认契约 v0.2.1 里 compose 应该用 `/health/live`（存活）还是 `/health`。确认后部署侧改一行即可。
4. **worker、beat、ingest、signal-rt 的入口。** 请提供启动命令，例如 `python -m app.jobs.worker` 或 celery 命令行，以及各自的健康检查方式（心跳 key、HTTP 端口或命令）。部署侧会复用同一个镜像来替换占位。
5. **ingest 心跳。** 目前 /health 一直是 degraded，因为 ingest 是 stale。ingest 入口落地后，心跳要写到 `INGEST_HEARTBEAT_KEY`。
6. **未提交的 pyproject/uv.lock（sqlalchemy、alembic）和 app/db/。** 提交时两个文件要一起提交，否则 `uv sync --frozen` 会因为 lock 和 pyproject 不一致而构建失败。如果需要 alembic 迁移，请约定由谁执行（单独的 migrate 一次性服务，或 api 启动前钩子），以及 alembic.ini 和迁移目录放在哪里。
7. 本次**没有发现**后端代码在容器内运行不了的问题，依赖和导入路径都正常，不需要后端修复。
