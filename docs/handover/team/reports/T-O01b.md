# T-O01b 报告：迁移进镜像 + 一次性 migrate + worker 类改用后端镜像 + nginx 方法透传

- 结果：**通过**
- 提交：`2dc2f1b`（deploy: T-O01b …），已快进推送；推送后远端 main = `2dc2f1b`（自 35f0139 前进，含他人提交 34641ae〔T-B02 v0.2.2〕、b864d97〔T-A03 文档，推送时位于我的提交之下，无法分开〕）。
- 未推送：本地 main 上在我之后又出现了 dd24549、56e1a65（架构文档，他人提交），不在本任务范围，留给提交人自己推。

## 改动（8 个文件，均在 deploy/）
| 文件 | 改动 |
|---|---|
| deploy/docker/backend.Dockerfile | builder 阶段 `COPY alembic.ini ./`、`COPY migrations ./migrations`，compileall 也编译 migrations |
| deploy/docker/backend.Dockerfile.dockerignore | 加 `!alembic.ini`、`!migrations/` |
| deploy/compose/docker-compose.yml | ① 新增一次性 `migrate`（后端镜像，`alembic upgrade head`，restart "no"，依赖 postgres healthy，挂 config）；② 新增一次性 `timescale-apply`（postgres 同一镜像，自带 psql；只读挂 deploy/scripts 与 deploy/db/timescale，`AIA_PSQL_MODE=direct` + PG* 环境变量经网络连 postgres 执行 db-apply-timescale.sh；依赖 migrate 成功退出）；③ `x-app-depends` 增加 migrate、timescale-apply 两个 `service_completed_successfully`（api/worker/beat/ingest/signal-rt 都等迁移和策略完成）；④ worker/beat/ingest/signal-rt 改用 `*backend-image`，命令 `python -m app.workers.{worker,beat,ingest,signal_rt}`，健康检查 `python -m app.workers.healthcheck <服务名>`（interval 15s/timeout 5s/retries 3/start_period 20s），基础文件里给四个服务都挂 `../../confi<path>`（live 模式也有配置）；环境变量沿用 x-app-env（CONFIG_DIR、LOG_LEVEL、REDIS_URL、DATABASE_URL 全有）；MAIRUI_LICENCE 仍只在 ingest；⑤ api 健康检查改为 `${API_PREFIX}/health/live`；⑥ 删掉 python:3.13 占位镜像/占位命令/占位健康检查锚点 |
| deploy/compose/docker-compose.dev.yml | migrate 也挂源码（新迁移不用重建镜像）；注释更新 |
| deploy/scripts/lib/common.sh | 新增 `AIA_PSQL_MODE=direct`：aia_psql 不走 docker exec，直接用 psql + libpq 环境变量；默认行为（exec）不变 |
| deploy/scripts/db-apply-timescale.sh | direct 模式下库名取 PGDATABASE（不再 docker exec 读 POSTGRES_DB） |
| deploy/nginx/nginx.conf | `error_page 405 = <at>nginx_405`：nginx 自产的 405（TRACE 等）转入命名 location，/api/ 下原样（保留方法）反代给后端，由后端返回 405 + Allow；非 /api/ 路径仍由 nginx 回 405 并补 `Allow: GET, HEAD`。后端返回的 405 本来就原样透传（未开 proxy_intercept_errors） |
| deploy/scripts/up.sh | 注释写明启动顺序；结尾 `ps -a`，能看到一次性服务的退出码 |

占位命令：T-B02 四个入口（app/workers/worker.py、beat.py、ingest.py、signal_rt.py）和 healthcheck.py 都已存在，**不再需要占位命令**。注意这些入口目前是后端的常驻占位实现（T-B02 §8.2：写存活文件/心跳，不连外部服务，ingest 不读 licence），真实任务逻辑以后端后续任务为准。

## 验收（全新克隆，提交后再跑一次）
环境：`git clone` 到 /tmp/o01b（HEAD dd24549，含 2dc2f1b；之后只多了 2 个文档提交），`.env` 从 .env.example 生成，改 `COMPOSE_PROJECT_NAME=aia-o01b`、`NGINX_HTTP_PORT=18981`、`POSTGRES_HOST_PORT=15991`、`REDIS_HOST_PORT=15992`、`AIA_BACKEND_IMAGE=aia-backend:o01b`，`env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY deploy/scripts/up.sh`（默认 dev 叠加层）。

| 项 | 结果 |
|---|---|
| up.sh 退出码 | 0（`--wait` 全部达标） |
| migrate | Exited (0)；日志 `0001 → 0002` 两个版本都执行；alembic_version = 0002 |
| timescale-apply | Exited (0)；“完成：9 项，全部成功”，**无 SKIP**；10 个策略作业（压缩 5、保留 3、聚合刷新 2）、2 个连续聚合 |
| 其余 8 个容器 | nginx、api、worker、beat、ingest、signal-rt、postgres、redis 全部 healthy |
| 经 nginx GET /api/v1/health/live | 200；/health/ready 返回 db/redis/ingest 全 ok |
| 业务表 | app/market/ops/evaluation 4 个 schema 共 119 张表（含分区）；7 个 hypertable |
| 重复 up（AIA_UP_BUILD=0） | migrate、timescale-apply 再次 Exited (0)，策略脚本幂等 |

策略作业：minute_bars 压缩 7d/保留 1095d；realtime_quotes 压缩 7d/保留 21d；factor_values 压缩 90d；feature_bars_daily 压缩 30d；ingest_request_log 保留 30d；bars_5m 刷新 + 压缩 30d；bars_daily_from_1m 刷新。

### nginx 与直连对比
同一请求分别发往 `<url>` 与 `<url>`（compose 网络内的 curl 容器），比较状态码和 Allow 头：
7 个路径（health/live、health、meta/enums、openapi.json、me/profile、accounts、不存在路径）× 11 种方法（GET HEAD POST PUT PATCH DELETE OPTIONS TRACE TRACK PROPFIND FOO）= 77 组，**差异 0**。
例：TRACE /api/v1/health/live → 两边都是 `405` + `Allow: GET`；TRACE /api/v1/openapi.json → 两边都是 `405` + `Allow: GET, HEAD`。
对照（改前的 nginx.conf，同一网络）：TRACE /api/v1/health/live → `405 Not Allowed`，无 Allow 头（即测试看到的 4 个失败原因）。
非 /api/ 路径：TRACE / → 405 + `Allow: GET, HEAD`。
已知例外：`CONNECT` 在 nginx 解析请求行时就回 400，到不了任何 location，无法透传；契约测试的 unsupported_method 检查不使用 CONNECT。

清理：两次演练都 `down.sh -v`，容器/卷/网络已无残留，aia-backend:o01b 镜像已删，克隆目录已删。

## 注意事项
- 生产栈（aia-*）：本次开始时 docker 里**已没有任何 aia-* 容器**（不是我停的；卷仍在，我没动）。演练全程用独立项目名和端口，未碰 aia 项目的卷和数据。
- 第一次（打补丁的工作区）演练时没设 AIA_BACKEND_IMAGE，`aia-backend:local` 标签被重建为“main + 本次改动”的镜像；正式验收改用 aia-backend:o01b。aia 栈下次 up.sh 默认 --build，会按当时代码重建，无影响。
- timescale-apply 的镜像写了两处（postgres 与 timescale-apply 各一行，带 digest）：common.sh 的 `aia_compose_image` 用 awk 读 postgres 那行，不能改成 YAML 锚点。升级时两处一起改（文件里已注释）。
- `restart: "no"` 的一次性服务每次 `up` 都会重跑（迁移和策略均幂等）。迁移失败时 api 等服务不启动，up.sh 返回非 0，看 `compose.sh logs migrate timescale-apply`。

## 给后端 / 运维的后续建议（T-B02 报告里提的，本次未改）
- 策略脚本日志里出现 `WARNING: column "feature_set_version" should be used for segmenting or ordering`：policies.conf 里 market.feature_bars_daily 的 orderby 应加入 feature_set_version（建议 `feature_set_version, trade_date DESC`），否则压缩后同一 code/日期的不同版本混在一起。
- bars_5m 的 time_bucket offset（A 股 9:30 开盘对齐）按 T-B02 报告建议，需要后端确认口径后在 deploy/db/timescale/caggs/bars_5m.sql 调整。两项都要改已上线的压缩设置/连续聚合，需单独任务（含已有数据的迁移方案）。

---

## 追加（2026-11-01 14:05 MST）：评审 m6、413、CI 不用真实凭据、probes S1 窄豁免

### 提交与推送
- 6baa37b：nginx m6（X-Request-Id 透传）和 413 JSON 信封；CI 去掉 MAIRUI_LICENCE / DEEPSEEK_API_KEY 的引用；secret-exact 改为本机 pre-commit/pre-push。
- 37d454b：.gitleaks.toml 给 S1 加的窄豁免和配套自测。
- 远端 main 从 1d2fbda 快进到 **37d454b**，一共推了 7 个提交，按线性顺序：fce21bb（架构）→ fb583bf（策略文档）→ 3f04eda（后端 probes，删了前端 4 个文件，是编排者的决定，保留）→ 6baa37b（本角色）→ c68afb8（前端 T-F01，在我提交期间叠上来）→ ce38a3f（后端 T-B02a，同上）→ 37d454b（本角色）。别人的提交没有 rebase 过，没有改过。
- 推送前对 origin/main..37d454b 做了扫描：
  - gitleaks 0 处。
  - secret_scan range 共 74 个文件版本，阻断 0，告警 0。
  - 真实值精确比对：worktree 和这个区间都是 not-found。
  - 没有证书文件或 .env 文件。
  - merge-base 确认是祖先关系。

### nginx（deploy/nginx/nginx.conf）
- m6：用 `map $http_x_request_id $aia_request_id` 处理。
  - 传入值匹配 `^[A-Za-z0-9._:-]{1,128}$` 时原样透传。这个格式跟后端 `_SAFE_ID` 一致，契约 §1 本身没有规定格式。
  - 不匹配或没传时，用 `req_` 加上 nginx 的 32 位 hex `$request_id`，格式和后端生成的一致。
  - 处理后的值同时用在 proxy_set_header、access_log（log_format aia 的 request_id=）、405/413 的响应头和 413 的 body 里。
- 413：`client_max_body_size 26m`，配了 `error_page 413 <at>payload_too_large`。
  - 返回契约 §2 的信封：`{"error":{"code":"PAYLOAD_TOO_LARGE","message":"请求体过大","details":{"max_bytes":27262976},"request_id":…}}`。
  - Content-Type 是 `application/json; charset=utf-8`，带 X-Request-Id，Cache-Control 为 no-store。
  - 后端 config 里还没有上传上限的键，所以 26m 是按 plan §3.5 定的：单文件 ≤ 5 MB、最多 5 个文件，合计 25 MB，再给 multipart 开销留点余量。

### 验收（全新克隆 6baa37b，跑 up.sh）
- up.sh 退出码 0。migrate 跑了 0001→0002，timescale-apply 9 项全部成功，其余容器都 healthy，health/live 返回 200。
- 演练用的 compose 项目名实际是 aia-accept-o01a：shell 里导出的 COMPOSE_PROJECT_NAME 覆盖了 .env 里的 aia-o01c。这个名字独立于 aia，端口是 18981 / 15991 / 15992。
- 合法 id `o01c-test.valid:001`：响应头、api 日志的 `request_id=`、nginx 日志三处都是这个值。后端 404 信封里的 request_id 也是它。
- 不传 id：生成了 `req_e2f4692ee5d5fc314902723ab12888e6`，响应头、api 日志、nginx 日志三处一致。
- 非法 id 会被丢弃，换成新生成的 req_ id。测过含空格的、含引号的、129 字符的。正好 128 字符的照样透传。
- 413 的几种情况：
  - 28 MB（Content-Length）返回 413 加 JSON 信封，request_id 等于传入值。不传 id 时，头和 body 里是同一个新生成的 id。
  - chunked、multipart、非 /api 路径也都返回 413 JSON。
  - 25 MB 能到达后端（返回 404，因为 /imports 还没实现）。
- 405 对比重跑：在 nginx 容器内分别请求 <host> 和 api:8000，77 个组合的状态码、Allow、X-Request-Id 都没有差异，没有回归。
- 清理：执行了 down.sh -v，aia-accept-o01a 的容器、卷、网络都删了，aia-backend:o01c 镜像和克隆目录也删了。没碰 aia 项目，也没碰别人的容器。

### CI 不用麦蕊 / DeepSeek 真实凭据（详见 T-O02.md §7）
- 删掉了 secret-exact 作业，CI 里没有留下空作业。workflow 里不再引用任何 `secrets.*`。
- ci.yml 里麦蕊的 base URL 指向 <host>:9 兜底。
- 真实值比对改为本机 scripts/ci/check_real_secrets.sh，由 pre-commit 和 pre-push 钩子调用，不打印值。
- 已确认 CI 不运行 probes、ingest 和 worker，后端 app 没有 HTTP 客户端，CI 里没有任何步骤会请求麦蕊或 DeepSeek。

### probes/common.py:39 的 S1（ccf7cba）
- 比对结果：ccf7cba 里那一行的值（dry-run 虚构证书 DRY_RUN_LICENCE）和本机真实的 MAIRUI_LICENCE、DEEPSEEK_API_KEY 都不一样，相等和互相包含都不成立。check_real_secrets.sh history 的结果也是 not-found。全程没有打印任何值。
- 真实值的来源说明：本机仓库里的 deploy/env/.env 现在已经不存在了（之前也只有占位值），所以比对用的是本机 shell 环境变量里的真实值。
- 豁免方式：在 S1 规则下加了 `[[rules.allowlists]]`，`condition = "AND"`，三个条件必须同时满足：
  - 提交 = ccf7cba 的完整 sha；
  - 路径 = `^src/backend/probes/common\.py$`；
  - 命中内容的正则逐字匹配那个虚构值。

  没有整个文件豁免。正则里的写法避开了 S1 自己，所以 .gitleaks.toml 本身不会被 S1 命中。
- 效果：gitleaks 全量历史扫描里，这一条已经不再出现。新增的自测会验证：同路径同内容但提交不同时照样拦，换个路径也照样拦。CI 自测共 116 个，全部通过。

### CI 结果（37d454b：ci 运行 41349919364，secret-scan 运行 41349919352）
- 本角色负责的作业都是绿的：self-test、pip-audit、migrations、licenses、image，以及扫描作业里的 gitleaks 和 secret_scan 两个步骤。S1 的阻断已经消失。
- 别人的作业里，frontend 和 contract 也转绿了（来自 c68afb8 和 ce38a3f）。
- 还红的两个都是测试角色负责的夹具问题，原因和上次相同：
  - fixtures；
  - 扫描作业的最后一步「夹具一致性」。
- backend 没有测试，同样归测试角色（T-T01）。

### 遗留
- 后端 config 里没有上传上限的键，比如 import.max_file_bytes。nginx 的 26m 和 413 里的 max_bytes 27262976 都是按 plan §3.5 写死的，后端加键之后要同步。
- 后端错误响应的 Content-Type 是 `application/json`，没带 `; charset=utf-8`，跟契约 §2 不一致，归后端。
- 全量历史扫描（schedule 或手动的 history 模式）还会红：
  - gitleaks 和 secret_scan 都会报 ccf7cba 里 deploy/env/.env.example 第 15、21 行的 S4。那是改成 changeme 之前的旧占位值。
  - secret_scan.py 的 history 模式会报 probes 那一条 S1。Python 的允许清单只支持「路径」和「^字面量$」两种形式，不能写「提交+路径+内容」，所以这次只按要求加了 gitleaks 的豁免。
  - 两件事都需要编排者决定是否加窄豁免，或者让 history 模式只扫指定范围。
- 别人工作区里还有没提交的改动（src/backend/pyproject.toml、uv.lock、src/frontend 的多个文件）。本角色没动，也没暂存。
