# 评审报告：T-B02（含 T-B01 复审）

- 评审人：架构师；日期：2026-11-01（MST）
- 评审对象：`src/backend/`。提交 `9be15a0`（Alembic 基线）、`a8bafbb`（占位进程）、`34641ae`（契约 v0.2.2 同步）。T-B01 修复在 `f34fcfd`，运维的 B1 修复在 `96c1c8e`，两者一并核对。
- 依据：`docs/plan.md` §6.1（main，T-A02 合并口径）；`docs/api-contract.md` v0.2.2（`34641ae` 所在版本）；`reports/T-B02.md`、`review-T-B01.md`、`T-T01a.md` §7。
  契约 v0.2.3 已在 `b864d97` 提交。涉及 v0.2.3 的差异记为「待同步 v0.2.3」，**不算本次不通过**。
- 评审方式：只读。代码在独立 worktree `/tmp/rev-b02`（检出 `34641ae`）中运行，评审结束后已删除。没有改代码，没有动主仓库的 index 和工作区。

## 0. 结论

| 对象 | 结论 |
|---|---|
| **T-B01 复审** | **通过**。B1 和 M1–M8 都已修好。M9 改由测试侧跟踪（见 §2）。尚未处理的次要项（m4、m5、m7、m6 运维侧）不阻塞，已转入后续任务 |
| **T-B02** | **有条件通过**。没有阻断项。合入后续 T-B 任务之前，需要关闭 F1、F2（运维）和 F3（测试），F4–F6 可随后续任务一起处理 |

问题数（只算本次新发现的 T-B02 问题）：**阻断 0 · 主要 3 · 次要 5 · 建议 3**。另有「待同步 v0.2.3」5 项。

## 1. 实测结果（worktree `34641ae`）

| 项 | 结果 |
|---|---|
| `uv sync --frozen`；`ruff check`；`ruff format --check`；`mypy`（strict，40 个文件） | 全部通过，没有问题 |
| 测试分支 `d745148`（T-T01b）的 `tests/backend` + `tests/replay`，不含 integration | **456 通过 / 4 失败 / 90 跳过 / 4 预期失败（xfail）**。4 个失败全部出在测试侧，原因见 F3 |
| `tests/backend/integration`（testcontainers，timescale 2.31-pg16） | 4/4 通过 |
| `alembic upgrade head` → `alembic check` → `downgrade 0001` → `downgrade base` → `upgrade head` | 全部成功；`check` 输出 “No new upgrade operations detected” |
| 升级后检查数据库 | app 99、market 14、ops 2、evaluation 2 张基础表（含分区子表）；7 个 hypertable；45 张表有触发器；`user_profiles` 有 `trg_user_profiles_immutable`，新增 4 列均可为空；连续聚合 0 个（与后端报告的遗留项一致） |
| plan §6.1 的 5 个 YAML 代码块与 `config/*.yaml` 逐键比对（YAML 1.2 布尔规则） | 5 个文件**完全一致** |
| TestClient 抽查 | `DELETE /health/live` → 405，`Allow: GET`，`details.allowed=["GET"]`。`/admin/users` 与 `DELETE /admin/x` → 404，不带 Allow 头。`/health/ready` 在未配置 DB 和 Redis 时 → 503 `down/error/error/unknown`，`checked_at` 为 +08:00 时区，`version` 0.1.0。`/meta/enums`：`version` 为 v0.2.2，`import_codes` 46 个；带 `W/` 前缀的 ETag 和 `*` 都返回 304 |
| 运行时覆盖层 `with_business_overrides` | 只覆盖叶子键时，同级其他键保留；列表整体替换；`null` 视为未覆盖；未知键和类型错误都报 `ConfigError`，消息里不含取值；`model_dump` 后再校验能还原成相等对象 |
| 密钥检查 | `app/` 中没有任何地方读取 `MAIRUI_LICENCE` 或 `DEEPSEEK_API_KEY`。compose 中只有 ingest 注入 `MAIRUI_LICENCE`。`database_url` 和 `app_master_key` 都用 `SecretStr`；ingest 占位进程不发任何外部请求 |

## 2. T-B01 原有问题逐条复核

| 编号 | 状态 | 证据 |
|---|---|---|
| B1 nginx 去掉了 `/api` 前缀 | **已修**（运维 `96c1c8e`） | `deploy/nginx/nginx.conf:23-24` 的 `proxy_pass <url>` 不带 URI，原样转发 `/api/v1/...` |
| M1 405 | 已修 | `app/common/errors.py:324-333`：带 Allow 头和 `details.allowed`；`/admin/*` 对非管理员返回 404（`:319-321`，T-B03 前 `_is_admin_user` 恒为 False）；实测符合 |
| M2 `DATA_STALE` 重名 | 已修 | 错误码改为 `FRESH_DATA_REQUIRED`（`errors.py:78`、`:154`） |
| M3 `IMPORT_*` 混在错误码中 | 已修 | HTTP 错误码只保留 `IMPORT_FILE_ERRORS/ROW_ERRORS/WARNINGS_UNACKNOWLEDGED/NOTHING_TO_COMMIT`（`:48-51`）；scope 只有 http/internal（`:91`） |
| M4 health live/ready | 已修 | `app/api/v1/health.py:166`（live）、`:193-210`（ready 和别名）、`:184`（down 时返回 503） |
| M5 心跳格式 | 已修 | `health.py:96-124`：JSON 中 `ts` 为整数且不接受布尔值；判定顺序 paused → stale → ok；Redis 未配置或出错 → `(error, unknown)`。ingest 写心跳的代码在 `app/workers/ingest.py:27-52` |
| M6 `/meta/enums` 结构 | 已修 | `version`=CONTRACT_VERSION，含 `import_codes`；测试 `test_meta_enums.py` 通过 |
| M7 少 21 个枚举 | 已修 | `test_contract_v022.py` 和 `test_meta_enums.py` 都通过 |
| M8 严格加载 YAML | 已修 | `app/config_files.py`：`_Strict` 设了 `extra=forbid` 和 frozen，`schema_version` 为 `Literal[1]`；`config.py:59-75` 使用 YAML 1.2 布尔规则 |
| M9 没有测试 | **转测试侧** | main 上的 `tests/` 只有夹具，456 条后端用例在未合并的 `test/T-T01`（`d745148`）上。后端仓库本身仍然没有单测目录；按 plan §6，测试统一放在 `tests/`，由测试合入。见 F3 |
| m1 按键覆盖、三层优先级 | 已实现 | `config.py:131-168` 深合并，`:172-212` 环境变量白名单，`:334-350` 运行时覆盖层。“只能覆盖可热调的键”的白名单留给各管理端接口（文档已注明） |
| m2 YAML 中出现敏感键 | 已修 | `config.py:79-98`，但带来 F4 |
| m3 Redis 检查超时 | 已修 | 每个依赖单独 `asyncio.timeout(1s)`，并行 gather（`health.py:85`、`:137`、`:172`） |
| m4 日志仍是纯文本，不是 JSON | 未修（延后） | `app/common/logging.py:33`。转 T-B41 或可观测性任务 |
| m5 每个进程各自生成临时游标密钥 | 未修（延后） | 只影响 local/test，非 local 环境强制设置 `APP_MASTER_KEY`（`config.py:327-331`） |
| m6 nginx 覆盖客户端传入的 `X-Request-Id` | **未修（运维）** | `nginx.conf:28` 仍是 `proxy_set_header X-Request-Id $request_id;` |
| m7 未捕获异常把 traceback 写进日志 | 未修（延后） | `app/common/middleware.py:56` `error_logger.exception`。日志脱敏过滤器落地前，DSN 有可能进日志 |
| m8 If-None-Match 弱比较 | 已修 | `meta.py:327-332`，实测 `W/` 和 `*` 都返回 304 |
| S1–S4 | 延后，同意 | 不影响本阶段 |
| S5 契约前后不一致（403/404） | 已修（契约 v0.2.1 统一为 404） | — |
| S6 健康检查告警刷屏 | 已修 | `health.py:68-75`，只告警一次 |

## 3. T-B02 问题

| # | 级别 | 位置 | 依据 | 问题 | 修改建议 | 负责 |
|---|---|---|---|---|---|---|
| F1 | 主要 | `deploy/compose/docker-compose.yml:86-88`（api healthcheck） | 契约 §7.10 第 557 行：`/health/live` 用于容器健康检查，“依赖故障时不应重启 api” | healthcheck 探测的是 `/health`。v0.2.1 起它是 ready 的别名，DB 或 Redis 故障时返回 503，api 会被判为 unhealthy；注释“/health 恒返回 200”也已过时 | 改为探测 `${API_PREFIX}/health/live`，更新注释 | 运维 |
| F2 | 主要 | `deploy/docker/backend.Dockerfile:30-33`、`backend.Dockerfile.dockerignore`（白名单只有 pyproject/uv.lock/app） | plan §1.3 migrate 步骤；T-B02 §10 遗留项 | 镜像里没有 `alembic.ini` 和 `migrations/`，容器内不能执行 `alembic upgrade head`；compose 也没有 migrate 服务，worker/beat/ingest/signal-rt 仍用占位镜像 | dockerignore 白名单加入 `!alembic.ini`、`!migrations/`，Dockerfile 加 COPY；新增一次性 `migrate` 服务（`alembic upgrade head`），让 api 和 worker 等待它成功完成（`service_completed_successfully`）；占位进程改用 backend 镜像并配 `python -m app.workers.<name>` 和对应 healthcheck | 运维 |
| F3 | 主要 | 测试分支 `d745148`：`tests/backend/api_app/test_config.py:74-110` 中 4 条用例（`test_env_overrides_yaml_business`、`test_business_list_replaced_wholesale`、`test_business_null_means_not_overridden`、`test_business_merged_result_validated`） | plan §6.1：环境变量“仍只允许本节注明的键” | 这 4 条用例用整块 `BUSINESS='{"realtime":…}'` 环境变量测合并规则，后端按 plan 拒绝（`config.py:193-199` 抛 `ConfigError`）。**后端行为正确，用例与 plan 冲突**；不改的话，合入 main 后 CI 会红 | 合并规则改为通过 `Settings.with_business_overrides(runtime)`（运行时覆盖层）测试；环境变量层只测白名单内的 3 个心跳键（嵌套和扁平两种写法）；另加一条用例：整块 `BUSINESS` 或白名单外的 `BUSINESS__*` → `ConfigError`。改完后合入 main，M9 随之关闭 | 测试 |
| F4 | 次要 | `app/config.py:79-98`（`"api_key" in k`）；`:236-244`（`check_config_dir_files` 要求恰好 5 个文件）；`config_files.py` 中 `BUSINESS_FILES` | plan §6.1 的 `config/llm.yaml`（`api_key_env: DEEPSEEK_API_KEY`，只是变量名） | ① plan §6.1 已列出第 6 个文件 llm.yaml，后端还没有。② 放进 `config/` 后，api 会因为“多出文件”直接启动失败。③ 加上模型后，`api_key_env` 又会被敏感键检查拦下。测试已用 xfail 标记（指向 T-B25） | 可以放到 T-B25 做，但规则现在定下：凡以 `_env` 结尾、值匹配 `^[A-Z][A-Z0-9_]*$` 的键视为“变量名引用”，不算敏感；加 llm.yaml 时，`BUSINESS_FILES`、模型和 plan 比对测试同步更新 | 后端（T-B25） |
| F5 | 次要 | `app/config.py:268-273`、`:296-318`（`_ingest_keys_from_yaml`）、`:334-350` | plan §6.1 心跳键优先级；`config.py:188` 文档说“嵌套写法优先” | 同时设了 `INGEST_HEARTBEAT_KEY=a` 和 `BUSINESS__INGEST__HEARTBEAT__KEY=b` 时，实测 `settings.ingest_heartbeat_key == "a"`，但 `business.ingest.heartbeat.key == "b"`。ingest 和 health 读 `ingest_heartbeat_key`，其他读 business 的代码会拿到另一个值。另外 `with_business_overrides` 改心跳键后，`ingest_*` 三个字段不会跟着刷新（心跳键不可热调，影响小） | 去掉 `ingest_*` 三个顶层字段，改为只读属性，从 `business.ingest.heartbeat` 取值；扁平别名只在 `business_env_layer` 中处理（现状就是这样）。或者至少在两种写法取值不一致时启动失败 | 后端 |
| F6 | 次要 | `app/config.py:261-262` | B1 已修 | `api_prefix` 的注释还写着“nginx 会去掉 /api 前缀”，已过时 | 删除这段注释，或改成“与 nginx 原样转发对齐” | 后端 |
| F7 | 次要 | `app/common/errors.py:340-346` | 契约 §4 | 未映射的 413/415 统一改写成 400 `VALIDATION_ERROR`。导入上传超过大小上限时，客户端拿到的是 400，而契约 §4.1 期望 `IMPORT_FILE_TOO_LARGE` 体现在导入结果里 | 不必现在改；做导入时（T-B 导入任务）由上传接口自己判断大小并返回 `IMPORT_FILE_ERRORS`，不依赖框架的 413。需要的话请架构师在契约 §4 补一行 413 的写法 | 后端（导入任务）/ 架构师 |
| F8 | 次要 | `migrations/versions/0002_contract_v022.py:63-68` | plan §6.1 `rc2_position_cap.single_position_max_pct`：用户可调范围 5–50；契约 §7.1 `/me/profile` | `user_profiles.max_single_position_pct` 的 CHECK 是 `(0,100]`，比 plan 的 5–50 宽。新列允许为空，与后端说明一致，可以接受 | API 层（T-B03）按 5–50 校验；数据库层保持宽约束也行，但请在表注释写明“范围由 API 校验，以 risk_controls 为准” | 后端（T-B03） |
| F9 | 建议 | `app/workers/runner.py:109-117` | — | tick（写心跳）失败时仍然更新存活文件，ingest 容器会一直显示 healthy，而 `/health/ready` 里是 stale | 占位阶段可以接受；T-B04a 中改为连续 N 次失败就不再更新存活文件 | 后端（T-B04a） |
| F10 | 建议 | `app/workers/healthcheck.py:144` | — | 存活阈值固定为 `3 × 15` 秒；如果把 `ingest.yaml` 的 `heartbeat.interval_s` 调到 45 秒以上，健康检查会误判 | 阈值改为 `3 × max(15, interval_s)`，或者让存活文件按固定 15 秒节拍单独写 | 后端 |
| F11 | 建议 | `migrations/versions/0002_contract_v022.py:34-36` | — | 对只追加表做 drop column，旧列数据会丢；目前没有生产数据，可以接受 | 在 docstring 写明：“生产库有数据后禁止这种写法，改成新增列 + 视图过渡” | 后端 |

## 4. 待同步 v0.2.3（`b864d97`，不计入本次结论）

1. `CONTRACT_VERSION` 改为 `"v0.2.3"`（`/meta/enums.version`，同时更新 ETag 测试）。
2. `config/market_rules.yaml` 和 `MarketRuleSegment.risk_warning`：`applies_to_boards` 改为 `[main_board, chinext]`；新增键 `limit_order_only_exchanges: [SH]`，模型要加这个字段，否则 `extra=forbid` 会导致启动失败；回看段的注释也要更新。
3. `horizon_classifier.yaml` 发 1.1.0（`SH0C` novice 封顶 59）；结果加 `caps[]`（`HorizonCap`）、`snapshot_id`、`evidence[]`；`horizon_classifier_versions` 加 `semver` 列（唯一，需符合 semver 正则）。需要新迁移 0003。
4. 每个用户每只证券至多 1 张 `active` 建议卡：加部分唯一索引（0003）。
5. `DataProvider` 已经没有 `local`（`enums.py:281-285`），**已符合**；其余新增字段（TerminalRow `data_as_of`/`trade_date`、DailyReport `stocks[]` 字段、通知 204 等）随各自接口任务实现。

## 5. 谁做什么

- **运维**：F1（healthcheck 改用 `/health/live`）、F2（镜像包含迁移文件、加 migrate 服务、占位进程改用 backend 镜像）、m6（保留客户端传入的 X-Request-Id）。
- **测试**：F3（改 4 条配置合并用例后把 `test/T-T01` 合入 main，M9 随之关闭）。
- **后端**：F5、F6 尽快改（工作量小）；§4 的 v0.2.3 同步（新迁移 0003 和 YAML 模型）；F4 在 T-B25 做，F7 在导入任务做，F8 在 T-B03 做，F9 在 T-B04a 做；m4、m7 在可观测性任务中做。
- **架构师**：确认 F4 的“`*_env` 是变量名引用”规则，写进 plan §6.1 通用规则；按 F7 视需要在契约 §4 补 413 的写法；后端报告中的 C1–C8 另行答复。

## 架构师处理（2026-11-01 13:50）
- `*_env` 键约定已写入 plan §6.1（值为变量名引用，匹配 ^[A-Z][A-Z0-9_]*$，不当密钥拒绝）。后端在 T-B25 按此修 F4。
- 413：契约 v0.2.3 同日补充 `413 PAYLOAD_TOO_LARGE`（仅网关/框架上限；应用层超限仍 422 IMPORT_FILE_ERRORS）。运维 nginx 加 error_page 413 返回 JSON 信封，client_max_body_size 略大于应用上限。
