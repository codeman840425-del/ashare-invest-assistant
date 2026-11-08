# 代码评审：T-B01 后端骨架（commit 4b9cd8d）

- 评审对象：`4b9cd8d feat(backend): T-B01 后端骨架（FastAPI/配置/统一错误/request_id/游标分页/health/meta）`，17 个文件，+2810 行（其中 `uv.lock` 1145 行）
- 评审方式：在 `/tmp/review-tb01` 建 detached worktree 只读阅读；在 `/tmp/tb01-run` 的副本里跑 lint、类型检查和临时测试；**仓库内代码未改动**
- 对照基准：`docs/api-contract.md` v0.2、`docs/plan.md`（本地提交 4c75985）
- 评审人：架构（T-A01），2026-11-01 13:05 MST（美国山地时间；北京时间 2026-11-02 04:05）

## 1. 结论：**有条件通过**

代码质量高：结构清楚，类型完整，`ruff`（含 S/BLE/ANN 等规则）、`ruff format` 和 `mypy --strict` 全部通过。用脚本逐项比对，错误码（56 个）、枚举（37 个）、原因码（23 个）与**提交时的契约 v0.1** 完全一致。

主要问题有两类：

- **契约 v0.2 在本提交之后才定稿**，所以大部分偏差属于“同步项”，不算实现错误：405、FRESH_DATA_REQUIRED、IMPORT_* 命名空间、/health 拆成 live 和 ready、心跳 JSON、/meta/enums 的 version 和 import_codes、新增 21 个枚举。
- **另有两项不属于同步问题**：
  - 跨服务的 nginx 前缀问题会让经过 nginx 的所有 API 请求都返回 404；
  - 仓库里没有任何测试。

**通过条件**（在 T-B02 及之后的后端任务建在这个骨架上之前完成）：
1. B1 修复（nginx 由 T-O01 负责，后端配合确认）。
2. M1–M8 在 T-B01 的后续提交里同步到契约 v0.2。
3. M9 补上仓库内的单元测试。

次要和建议项可以排进后续任务。

| 严重度 | 数量 |
|---|---|
| 阻断 | 1 |
| 主要 | 9 |
| 次要 | 8 |
| 建议 | 6 |

工作区现状（只作背景，不在评审范围内）：当前工作区有未提交的修改：`errors.py`、`main.py`、`schemas/enums.py`、`pyproject.toml`、`uv.lock`，另有新增的 `app/db/`。从 diff 看，已经在处理 M1、M2、M3：

- 新增了 `METHOD_NOT_ALLOWED`，405 不再映射到 404；
- `DATA_STALE` 改为 `FRESH_DATA_REQUIRED`；
- IMPORT_* 移到 `IMPORT_CODE_TABLE`；
- 加了 `_is_admin_path`。

这些修改提交后需要复核。

## 2. 问题清单

行号以 commit 4b9cd8d 为准，路径相对 `src/backend/`（另有注明的除外）。

| # | 严重度 | 文件:行 | 契约/方案条款 | 问题 | 建议修复（只描述，不实现） |
|---|---|---|---|---|---|
| B1 | **阻断** | `deploy/nginx/nginx.conf:21-22`（T-O01）；`app/config.py:104`（`api_prefix`） | 契约 §1 基础路径 `/api/v1`；plan 1.3 容器清单 | nginx 配置是 `location /api/ { proxy_pass <url> }`，带结尾 `/` 会把 `/api` 去掉，后端实际收到 `/v1/...`。而后端路由注册在 `/api/v1`，所以**经过 nginx 的所有 API 请求都是 404**，前端联调会整体失败。T-B01 报告已经提到这个问题，但还没定下来怎么改 | 统一为“nginx 保留前缀”：`proxy_pass <url>`（不带 URI），后端维持 `API_PREFIX=/api/v1`。由 T-O01 改 nginx，并加一条冒烟检查：经 nginx 请求 `GET /api/v1/health/live` 应返回 200。不要用改 `API_PREFIX` 的方式迁就 nginx，否则 OpenAPI 路径会和契约不一致 |
| M1 | 主要 | `app/common/errors.py:255`、`:317` | 契约 §4 `405 METHOD_NOT_ALLOWED`（带 `Allow` 头，`details.allowed`）；§9 测试要点 | 405 被映射成 `404 NOT_FOUND`，`Allow` 头还被主动删掉。实测：`DELETE /api/v1/meta/enums` 返回 404，没有 Allow 头 | 新增 `METHOD_NOT_ALLOWED`（405），保留 `Allow` 头，`details={"allowed": [...]}`。`/admin/*` 的例外见 S5，等契约澄清后再实现 |
| M2 | 主要 | `app/common/errors.py:76`、`:151` | 契约 §1 命名规则：错误码、原因码、导入提示码三个命名空间不得重名；§4 `FRESH_DATA_REQUIRED` | 错误码 `DATA_STALE` 和原因码 `DATA_STALE` 重名。比对脚本检出的唯一冲突就是这一个 | 改名为 `FRESH_DATA_REQUIRED`（503）；在测试里检查三个命名空间不相交 |
| M3 | 主要 | `app/common/errors.py:46-47`、`:58`、`:89`、`:121-122`、`:133`、`:202-203` | 契约 §4 / §4.1：`IMPORT_*` 提示码不是 HTTP 错误码；`error_codes[].scope` 只有 `http` / `internal` | `IMPORT_DUPLICATE_FILE`、`IMPORT_UNRECOGNIZED_FORMAT`、`IMPORT_ROW_COLUMN_MISMATCH` 放在 ErrorCode 里，`ErrorScope` 里还有 `row`。同时缺少 v0.2 的 3 个 HTTP 码：`IMPORT_FILE_ERRORS`、`IMPORT_WARNINGS_UNACKNOWLEDGED`、`IMPORT_NOTHING_TO_COMMIT` | 把 §4.1 的 46 个提示码集中到枚举模块（code、severity、scope、needs_action），从 ErrorCode 里删掉这 3 个；`ErrorScope` 去掉 `row`；补上 3 个 HTTP 码。最终 ErrorCode 应为 57 个 |
| M4 | 主要 | `app/api/v1/health.py:1-8`、`:31-37`、`:110-116` | 契约 §7.10：`/health/live` 恒 200；`/health/ready` 在 db 或 redis 出错时返回 503 `down`，只有 ingest 异常时返回 200 `degraded`；带 `checked_at`、`version`；`/health` 是 ready 的别名 | 只有 `/health` 一个端点，HTTP 状态恒为 200，`status` 没有 `down`，响应里缺 `checked_at` 和 `version`。实测 `/health/live` 和 `/health/ready` 都是 404；db 和 redis 都失败时仍返回 200 `degraded` | 拆成 live 和 ready 两个端点（live 不访问任何依赖），按契约给出状态码和 `health_status`。compose 和 Docker 的 healthcheck 改用 live（依赖故障时不应重启 api），nginx 和监控用 ready。响应体不用错误外壳 |
| M5 | 主要 | `app/api/v1/health.py:28`、`:66-73`、`:86`、`:98` | 契约 §7.10 心跳：值为 JSON `{ts, instance_id, leader, version, budget_used_last_minute, queue_depth}`；判定顺序：Redis 不可用 → `unknown`，然后 paused，然后 stale（超过 120 秒），否则 ok | 心跳按纯 Unix 秒数解析。实测：符合契约的 JSON 心跳被判成 `stale`，旧格式的纯数字反而是 `ok`。Redis 不可用时返回 `stale`，应为 `unknown`；`IngestState` 里也没有 `unknown` | 用 `json.loads` 解析，只取 `ts`（整数），解析失败按 stale 处理。Redis 不可用时返回 `unknown`。判定顺序按契约实现，阈值继续用 `INGEST_STALE_AFTER_S`（默认 120）。`paused` 的值是 JSON `{by, at, reason}`，ready 只看键是否存在 |
| M6 | 主要 | `app/api/v1/meta.py:57-63`、`:79-82` | 契约 §7.10 `/meta/enums` 结构：`version: "v0.2"`、`import_codes[]`；`error_codes` 里不放 IMPORT_* 提示码 | 实测响应只有 `enums`、`error_codes`、`reason_codes`、`risk_control_labels` 四个键，缺 `version` 和 `import_codes`；`error_codes` 里还有 `scope=row` 的条目 | 加上 `version` 和 `import_codes`（来自 M3 的集中表）；ETag 改为对含 version 的内容做哈希 |
| M7 | 主要 | `app/schemas/enums.py:204`（ImportStatus）、`:361`（CONTRACT_ENUMS） | 契约 §3 v0.2 | 和 v0.2 的 §3 相比少了 21 个枚举：`bar_adjust`、`bar_freq`、`card_risk_level`、`component_health`、`data_provider`、`dedup_status`、`executability_status`、`gap_reason`、`health_status`、`import_row_status`、`import_scope`、`import_severity`、`ingest_health`、`market_session`、`notification_target_type`、`reconciliation_item_kind`、`reconciliation_status`、`registration_mode`、`signal_kind`、`source_kind`、`strategy_eval_state`。`import_status` 还是 v0.1 的取值（`preview_ready` / `confirmed`，缺 `discarded`），v0.2 为 `previewed` / `committed` / `discarded`。另外 `enums` 里多了 `reason_code` 键，契约规定它只在 `reason_codes` 里展开 | 按 §3 v0.2 补齐，并修正 import_status；`enums` 的键集合应等于 §3 的表名（不含 reason_code）。加一条测试解析契约 §3 后做比对，比对思路同本评审的脚本 |
| M8 | 主要 | `app/config.py:46-69`（`load_yaml_dir`）、`:72-85` | plan 6.1 通用规则：每个文件必须有 `schema_version: 1`，未知键在启动时失败（pydantic `extra="forbid"`），只放非敏感参数 | YAML 读进来是任意 dict，不校验 `schema_version`，也没有按文件定义的 pydantic 模型。实测：缺 `schema_version` 且带拼写错误键（`foo_typo`）的 `ingest.yaml` 能正常加载 | 按 plan 6.1 为 realtime、ingest、market_rules、risk_controls、horizon_classifier 各建一个 `extra="forbid"` 的模型，`schema_version: Literal[1]`；未知文件名、未知键都在启动时报错。另加一条测试检查“YAML 默认值等于 plan 6.1 表格” |
| M9 | 主要 | 整个提交（无 `tests/` 目录） | plan 第 8 节 T-B01 验收；7.x 测试矩阵 | 提交里没有任何测试。`pyproject.toml` 列了 pytest 和 httpx，但 `pytest` 收集不到用例。T-B01 报告说的“测试”只在 /tmp 里跑过 | 至少补上以下单元测试：错误外壳（404、405、400、500）、422 转 400 的 fields 格式、request_id 透传与重新生成、游标往返（篡改、换 scope、过期）、limit 上限、health 的 live/ready 状态码与心跳判定、`/meta/enums` 的结构与 ETag/304、配置加载失败的各种情况、三个命名空间不重名。CI 跑 `uv run pytest` |
| m1 | 次要 | `app/config.py:148-164` | plan 6.1 优先级：环境变量（只限注明的键）> 管理端运行时覆盖 > YAML | 环境变量只能整体覆盖 `business` 字段，不能按键覆盖；也没有“运行时覆盖”这一层的接口 | 先定义 `get_business_config(name)` 这类读取接口，把三层合并的逻辑放在里面（运行时覆盖可以先是空实现，等 DB 任务接入）；允许 env 覆盖的键用白名单写明 |
<redacted:sensitive-value-or-command>
| m3 | 次要 | `app/api/v1/health.py:92` | 契约 §7.10：每个依赖检查超时 1 秒 | Redis 检查的总超时是 `timeout*2`，即 2 秒 | 改为 1 秒，或者把 PING 和读心跳分开各自限时，保证总时长不超过 1 秒 |
| m4 | 次要 | `app/common/logging.py:14` | plan 1.1 可观测性：结构化 JSON 日志加 `request_id` | 日志是纯文本格式，不是 JSON | 改用 JSON formatter（字段：ts、level、logger、request_id、msg），本地可以保留文本格式开关 |
| m5 | 次要 | `app/common/pagination.py:38` | plan 1.3：api 跑 uvicorn 2–4 个 workers | local/test 环境没设 `APP_MASTER_KEY` 时，每个进程用自己的临时密钥。多 worker 下游标会随机失效（返回 INVALID_CURSOR） | workers 大于 1 时要求设置 `APP_MASTER_KEY`，或在启动时给出明确告警；compose 的 local 叠加层给一个固定的开发用 key（不入库，只放在 .env 示例里） |
| m6 | 次要 | `deploy/nginx/nginx.conf:24`（T-O01） | 契约 §1：客户端可以传入 `X-Request-Id` | nginx 无条件用 `$request_id` 覆盖这个头，客户端传入的值会丢失 | nginx 用 `map $http_x_request_id` 处理：客户端传了就用客户端的，没传再用 `$request_id`。后端的安全正则仍然生效 |
| m7 | 次要 | `app/common/middleware.py:56` | plan 7.4A：日志不能含密钥 | 未捕获的异常会把完整 traceback 和异常消息写进日志。异常消息里可能带 DSN 或 URL 片段（实测会原样记录异常文本） | 加一个日志脱敏 filter，处理 DSN 中的密码、S1/S2 形式的 licence 和 key、`Authorization` 头；并加测试确认 |
| m8 | 次要 | `app/api/v1/meta.py:105` | RFC 9110 If-None-Match 用弱比较 | `If-None-Match: W/"…"` 和 `*` 都匹配不上，实测返回 200 | 比较前去掉 `W/` 前缀，并支持 `*` |
| S1 | 建议 | `app/main.py:31` | plan 7.x 安全 | 生产环境也公开 `/api/v1/openapi.json`。docs 页面已经只在 local/test 开启 | 生产环境关闭 openapi，或只给管理员看；前端的 TS 类型在 CI 里生成，不依赖线上接口 |
| S2 | 建议 | `app/common/pagination.py:61-81` | 契约 §1.2 | 游标只绑定了 scope，没有绑定过滤参数和 user_id。换一组筛选条件复用同一个游标，结果会不一致（不算越权，因为查询本身按用户过滤） | 把过滤参数和 user_id 的哈希放进游标，不一致时返回 INVALID_CURSOR |
| S3 | 建议 | `app/main.py`（无 CORS） | 契约 §1.3；plan 1.3（同源 nginx） | 没有配置 CORS，同源部署下这样是对的。CSRF 和会话不在 T-B01 范围（属于 T-B02） | 在 README 或配置注释里写明“不开 CORS”，再加一条测试确认没有 `Access-Control-Allow-Origin` 头。T-B02 的 CSRF 中间件要放行 GET、`/health*` 和 `/meta/enums` |
| S4 | 建议 | `app/api/v1/health.py:76-98` | — | 每次健康检查都新建一次 PG 和 Redis 连接 | 后续接入应用级连接池以后改为复用（只需检查超时，不需要新连接） |
| S5 | 建议（契约侧，架构负责） | `docs/api-contract.md` §1.3、§4 的 405 行、§9 | — | 契约自身前后不一致：§1.3 写“非 admin 访问 `/admin/*` 返回 403 FORBIDDEN”；§4 的 405 行写“非管理员访问 `/admin/*` 一律返回 404”；§9 写“`/admin/evaluation/*` 返回 404，其余 `/admin/*` 返回 403”。工作区里的 `_is_admin_path` 按全部 404 实现 | 架构在 v0.2.1 里统一口径（建议：普通用户访问任何 `/admin/*` 路径、用任何方法，一律 404，不暴露其存在）。后端等口径确定后再定实现 |
| S6 | 建议 | `app/api/v1/health.py:48-51` | — | 没设 `DATABASE_URL` 时，每次探测都打一条 WARNING，日志会被刷屏 | 改为启动时告警一次，或做限频 |

## 3. 已核实无误的部分

- **错误外壳**：结构固定为 `{error:{code,message,details,request_id}}`，`request_id` 与响应头 `X-Request-Id` 一致。404、400、500 都已实测；500 的响应里不含异常文本。
- **422 转 400**：统一为 `400 VALIDATION_ERROR`，`details.fields[].field/issue` 的格式与契约示例一致（例如 `limit` 对应 `must be <= 200`）。
- **request_id**：
  - 客户端传入的安全值（`^[A-Za-z0-9._:-]{1,128}$`）原样透传；
  - 含空格或换行等非法值时，改为生成 `req_` 加 32 位十六进制；
  - 所有响应都带这个头，包括错误响应和 304；
  - 通过 contextvar 写入每条日志；
  - 中间件是纯 ASGI 实现，不会缓冲 SSE。
- **游标分页**：
  - 格式为 base64url 编码的 JSON 加 HMAC-SHA256（截断到 128 位），密钥由 `APP_MASTER_KEY` 派生；
  - 篡改、换 scope、过期（24 小时）、格式错误都统一返回 `400 INVALID_CURSOR`；
  - `build_page` 按 limit+1 取数判断是否还有下一页，响应为 `{items, next_cursor}`，最后一页 `next_cursor` 为 null；
  - limit 默认 50，最大 200，0 和超上限都返回 400。
- **大小写**：普通枚举值是 snake_case，码类取值是 UPPER，`gate` 为 G1–G7，`risk_control_labels` 为 RC1–RC6，均与契约 §1 一致。
- **原因码**：23 个，`release_kinds`、`check_on`、`manually_releasable` 与 §6.1 一致。
- **`/meta/enums`**：
  - 不需要登录，`Cache-Control: public, max-age=300`；
  - 强 ETag 由内容哈希得出，匹配时返回 304 且响应体为空；
  - 取值全部来自集中定义，路由里没有写死。
- **配置**：
  - 不启用 dotenv，不读取 `MAIRUI_*`；
  - 数据库 URL 和主密钥用 `SecretStr` 保存，repr 里不显示明文（已实测）；
  - 非 local/test 环境必须设置 `APP_MASTER_KEY`，长度至少 32；
  - Settings 是 frozen；
  - YAML 解析失败或顶层不是映射时会报错，同名的 `.yaml` 和 `.yml` 也会报错。
- **健康检查**：db 和 redis 并行检查、有超时；响应里没有错误细节，日志只记异常类型，不记 DSN。
- **管理端**：本提交没有 `/admin/*` 路由，404 隐藏这一项不适用（口径问题见 S5）。
- **安全**：
  - 访问日志只记方法、路径（不含查询串）、状态码和耗时；
  - docs 页面只在 local/test 开启；
  - 后端不直接调用麦蕊。

## 4. 检查与测试结果（均在 /tmp 副本中执行，未改动仓库）

| 项 | 结果 |
|---|---|
| `uv sync --frozen`（uv 0.13.6，CPython 3.12.16） | 成功 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 15 个文件均已格式化 |
| `mypy`（strict，含 pydantic 插件） | 15 个源文件无问题 |
| 仓库内 pytest | **没有测试用例**（见 M9） |
| 评审临时测试 `/tmp/tb01-run/tmp_tests/test_review.py`（16 个，未进仓库） | 16 个全部通过。断言只覆盖第 3 节列出的正确行为；偏差以输出记录，见下 |
| 契约比对脚本 `/tmp/plan/cmp.py` | 对 v0.1（提交时的版本）：错误码 56/56、枚举 37/37、原因码 23/23 全部一致。对 v0.2：错误码缺 5 个、多 4 个，枚举缺 21 个，import_status 不一致，命名空间冲突 1 处（DATA_STALE） |

临时测试记录到的偏差（对应第 2 节）：

- `DELETE /api/v1/meta/enums` 返回 404 `NOT_FOUND`，没有 Allow 头（M1）。
- `/health/live` 和 `/health/ready` 都返回 404；db 和 redis 都没配置时，`/health` 返回 200 `{status: degraded, db: error, redis: error, ingest: stale}`（M4）。
- 心跳判定：纯 Unix 秒数判为 `ok`；**符合契约的 JSON 心跳判为 `stale`**；超过 121 秒判为 `stale`；Redis 不可用时返回 `(error, stale)`，应为 `unknown`（M5）。
- `/meta/enums` 的键只有 `enums`、`error_codes`、`reason_codes`、`risk_control_labels`；`version` 和 `import_codes` 都不存在；enums 37 个，error_codes 56 个（M6、M7）。
- 配置加载：未知键和缺少 schema_version 都被接受；YAML 里的 `mairui_licence` 键也被接受（M8、m2）。
- `If-None-Match: W/"…"` 返回 200（m8）。

## 5. 后续

- **后端（T-B01 后续提交）**：按 M1–M9 同步契约 v0.2 并补测试。提交后由架构复核，重点看：命名空间测试、health 状态码、心跳 JSON、`/meta/enums` 键集合。
- **T-O01**：B1（nginx 前缀）、m6（request_id 透传）、healthcheck 改用 `/api/v1/health/live`。
- **架构**：S5（admin 访问的口径）在契约 v0.2.1 中统一。
