# T-B02a 报告：数据模型第二轮 + 契约 v0.2.3 同步

- 执行：后端　日期：2026-11-01（America/Denver）
- 结果：**通过**；本地提交 **ce38a3f**（未推送；未 amend/rebase/reset）
- 提交内容（13 个文件，pathspec 提交，只含本人路径）：config/{market_rules.yaml, horizon_classifier.yaml, llm.yaml(新)}；src/backend/app/{config.py, config_files.py, common/errors.py, schemas/enums.py, api/v1/meta.py, db/base.py, db/tables/{signals,strategy,realtime}.py}；src/backend/migrations/versions/0003_t_b02a_contract_v023.py(新)
- 未碰：tests/、src/frontend、deploy、.github、docs、scripts、src/backend/probes/（steering #3）；config/strategies/ 未手写。未调用麦蕊（所有容器、测试均 `env -u MAIRUI_LICENCE`，并在 `unshare -rn` 断网下跑），STOP 保留（sha256 02339d1e…7fbe17 不变）。

## 1 数据模型（迁移 0003，Revises 0002；0001/0002 未改）
- 三层表、按月分区、不可变触发器、market_rule_versions、event_definitions：0001 基线已建；本轮补齐 3A.6 余项：
  - `candidate_signals`（分区父表，约束下沉到所有分区）CHECK：confidence∈[0,1]；rule_refs 每项 RuleRef（rule_id 非空、role∈rule_role、dimension∈dimension（v0.2.3 所有 role 必填）、passed 为布尔或 null）；evidence 每项 id 非空、provider∈data_provider；counter_evidence / invalidation 每项 text 非空。实现为 SQL/JSON path，先判类型再比值（lax 模式下否则会漏判）。迁移中的字面量与 ORM metadata 逐字一致（alembic check 无差异）。
  - 部分唯一索引：`suggestions (user_id, security_code) WHERE status='active'`（契约 #18）。
  - `horizon_classifier_versions.semver`（NOT NULL、唯一、semver 正则；表只追加，**升级要求表为空**，否则明确失败）。
  - `symbol_horizon_assessments`：`caps jsonb NOT NULL DEFAULT '[]'`（HorizonCap[]）、`evidence jsonb`；`inputs_missing` 每项匹配 `^f\.[a-z0-9_]+$`。
  - TRUNCATE 防护（超出 plan 字面，保守加强）：0001 触发器只拦 UPDATE/DELETE，新增语句级 `app.reject_truncate()` 挂在所有只追加/受限表（分区父表与现有子分区；普通表也挂——pg_partition_tree 对普通表不返回行，已用 UNION 本表修正）；`ensure_monthly_partitions` 新建分区时自动挂防护。
- 验收：upgrade→downgrade→upgrade 往返通过（含 deploy/scripts/db-apply-timescale.sh）；downgrade 后 pg_dump 与 0002 一致（只差 \restrict 随机令牌）；`alembic check` 无差异；TimescaleDB 容器内跑通。
- 自测：DB 自测 159/159（CHECK 各分支正/反例、UPDATE/DELETE/TRUNCATE 触发器、分区自动建与挂防护、部分索引唯一冲突、semver）。

## 2 配置（config/ 全部 yaml 对照 plan §6.1）
- market_rules.yaml（T006b §7 + plan）：50 万股上限 `applies_to_boards: [main_board, chinext]`（科创板不适用）；限价申报 `limit_order_only_exchanges: [SH]`；两段按生效日期分段（2026-07-06 / 2023-04-10），写全不继承；校验模型同步（新键 extra=forbid 校验、板块/交易所取值校验）。
- horizon_classifier.yaml：version_no 2、classifier_version "1.1.0"（semver 校验）、SH0C、IT0C。
- llm.yaml：新建，键与默认值逐字取自 §6.1，纳入加载（extra=forbid、深合并）。
- 对照脚本：7 个 yaml 与 plan §6.1 解析后 **diffs = 0**（含架构师 fce21bb 后的 horizon_classifier）。§6.1 未出现的键没有新增；无需标 TODO 的键。
- `*_env` 约定：敏感键检查不再误拦 `api_key_env` 这类只存环境变量名的键（值须为合法变量名）；真正存密钥值的键（api_key、password、secret、token 等）仍拦截，自测覆盖两侧。

## 3 T-T01b 并入项
1. 版本号：唯一来源是 `app/schemas/enums.py` 的 `CONTRACT_VERSION`，`/meta/enums` 直接引用；meta.py 文档/示例同步。现统一为 **v0.2.3**（覆盖 v0.2.2）。测试报告里的 v0.2.1 判断为旧代码/旧镜像所致（34641ae 已是 v0.2.2，代码中无其他版本字面量；剩余 "v0.2.1/v0.2.2" 仅为历史注释：enums.py:745、db/tables/llm.py:1,3、users.py:131）。CI 方式复核：`dump_meta_enums.py`（须在 src/backend 下运行，否则 `No module named app`）→ `check_contract.py` 通过（v0.2.3，error_codes=58 含 PAYLOAD_TOO_LARGE，reason_codes=23）；`check_code_namespaces.py` 通过。
2. BUSINESS null 语义：按 plan §6.1「值显式为 null 视为未覆盖，不能用来删除键」实现——映射逐键递归，列表与标量整体替换，null 跳过；构造参数 `Settings(business={...})` 层同样剔除 None。合并结果再整体严格校验。
3. llm.yaml + 敏感键：见 §2。

## 4 review-T-B02 处理（「T-B02 评审处理」）
| 条目 | 处理 |
|---|---|
| F1/F2 | 运维 2dc2f1b 已修 |
| F3 | 测试侧（T-T01c 已改为经 `Settings.with_business_overrides` 测） |
| F4 | 已做：`*_env` 约定 + llm.yaml |
| **F5** | 已修：扁平与嵌套两种写法同一键取值不同 → 启动 ConfigError（消息只含变量名、不回显取值）；运行时覆盖刷新 ingest_* 派生值。未改成 property，因测试使用 `Settings(ingest_stale_after_s=10)` |
| **F6** | 已修（注释与实现一致） |
| F7 | 413 → `PAYLOAD_TOO_LARGE` 信封；应用层导入大小超限仍为 422 |
| F8 | 归 T-B03（max_single_position_pct 5–50） |
| F9 | 归 T-B04a |
| F10 | 暂缓，建议阈值取 `3×max(15, interval_s)` |
| F11 | 写进 0003 docstring：生产有数据后禁止对只追加表 drop column，改「加列 + 视图过渡」 |
| m4/m7 | 可观测性任务；m6 运维（6baa37b 已做） |

## 5 契约 v0.2.3 同步（steering #2 / #3）
- market_rules、horizon classifier 1.1.0、迁移 0003（编号与本轮合一）、`*_env` 约定、413 `PAYLOAD_TOO_LARGE`、版本 v0.2.3：均已做。
- 413 details 契约为 `{max_bytes}`（可选）；nginx 直接返回时由运维信封给出，应用框架映射时 details 多为 null。
- **新手封顶**：按架构师 fce21bb 的落点实现（不再是“待定”）：只写在 `config/horizon_classifier.yaml` 对应周期的 `requires` 中——short.requires `SH0C`、intraday_t.requires `IT0C`（`input: profile.experience, op: in, value: [intermediate, advanced], else_cap: 59`，reason 文本与 plan 逐字一致）；不在 hard gates、不在代码中硬编码。加载校验沿用 requires 规则模型（else_cap 0–100、与 else_score 互斥），自测覆盖 IT0C 与 SH0C 同口径、位置正确。
- **与编排者口径的差异（需确认）**：编排者要求“把 IT0C 加进 reason-code 枚举和 /meta/enums”。按 fce21bb 与契约，SH0C/IT0C 是 `HorizonCap.rule_id`（规则 ID），**不是** `reason_code`：契约 §3 写明 reason_code「见 6.1（23 个）」，§6.1 为不可执行原因码，SH0C 也从未在其中；加入会让 CI check_contract 失败。按“最保守、不自行改方案”，**未加入 reason_code**，自测断言 reason_codes 仍为 23 个且不含 SH0C/IT0C。如确需在 /meta/enums 下发规则 ID，需架构师先改契约。
- probes：未动（S1 修复由该工作流负责）。

## 6 验证
- API 自测 167/167（含 /meta/enums v0.2.3 + 413、null 语义、F5、*_env、llm.yaml、market_rules 分段与校验、IT0C）。DB 自测 159/159。workers 测试通过。
- CI 同款 lint（src/backend）：`ruff check .`（含 S 规则）0 问题；`ruff format --check` 通过；`mypy --strict`（files=app）40 个文件无错误。
- 全栈 compose（`env -u MAIRUI_LICENCE deploy/scripts/up.sh`）：api/worker/beat/ingest/signal-rt/postgres/redis healthy；容器内 /meta/enums → v0.2.3、error_codes 58、含 PAYLOAD_TOO_LARGE、reason_codes 23；/health/ready 200；alembic_version=0003。nginx 未起（启动被中断；同机还有运维的 aia-accept-o01a 栈），故经 nginx 的 413 未在本轮复验，由运维 T-O01b 覆盖。之后 `down.sh -v`、删除 deploy/env/.env、清理 __pycache__（运维的 aia-accept-o01a 栈未动）。
- 测试工作树 wt-tests-T-T01（235a248，只读运行）：462 passed，5 failed，4 xfailed，4 errors。失败均为测试侧快照过期：`CONTRACT_VERSION='v0.2.2'` 期望（契约文件已是 v0.2.3）×3、plan §6.1 market_rules / horizon_classifier 快照未同步 ×2；4 个 xfail 同样以 plan v0.2.2 为基准。4 个 error 是 integration 用例在断网沙箱里连不上 docker，与本改动无关。
- 密钥扫描：gitleaks（临时索引）no leaks；scan_licence.py 未命中；rg 密码/密钥字面量无命中。

## 7 TODO / 待定
- suggestion_versions / evidence_items 在 plan 中未定义，未建表。
- Evidence id 在同一信号内唯一：DB 未约束（jsonpath 难以表达），在应用层做。
- 只能用于退出的规则（exit-only）在应用层校验。
- llm 相关枚举留给 T-B25。
- stops / snapshot_id 可空性 plan 未写明，沿用 0002。
- semver 列要求升级时表为空（见 §1）。

## 简短回报
- T-B02a：**通过**，提交 **ce38a3f**（本地，未推送）。
- 需要谁做什么：
  - 运维：推送 ce38a3f。
  - 测试：同步 v0.2.3 版本常量与 plan §6.1 快照（market_rules、horizon_classifier 1.1.0），更新相关 xfail。
  - 架构师 / 编排者：确认 IT0C 只作 HorizonCap.rule_id、不进 reason_code（编排者要求加入，但与契约 §6.1 冲突，本轮未加）；复审 TRUNCATE 防护与 semver 空表前提。

---

## 补充（编排者 14:06 两项，提交 045c550）

1. **请求体上限**
   - 新键 `ingest.imports.{max_file_bytes: 5242880, max_files_per_upload: 5, max_request_bytes: 27262976}`（pydantic `IngestImports`，extra=forbid，校验 `max_request_bytes > max_file_bytes × max_files_per_upload`）。值来自 plan §3.5（单文件 ≤ 5 MB、单次 ≤ 5 个，MB 按 MiB，与 nginx 同口径）；框架层上限 = nginx `client_max_body_size 26m`（deploy/nginx/nginx.conf 只读核对，未改）。
   - plan §3.5 与 nginx **一致**（26 MiB > 25 MiB 应用上限，符合契约“网关上限须略大于应用上限”）。
   - **偏差**：plan §6.1 的 `ingest.yaml` 代码块没有这一块，而规则是“键和默认值以 plan §6.1 为准”，测试 `test_repo_yaml_equals_plan_defaults[ingest]` 也比对 YAML == plan。所以 YAML 里**以注释形式**给出这一块，生效默认值在模型里（值相同，自检断言两者一致）；`ingest.yaml` 缺这一块照常加载。
   - 接线：新 `BodySizeLimitMiddleware`（在 RequestId 内层）。`Content-Length` 超限直接返回 413；分块累计超限抛 `PayloadTooLarge`，最终返回 `413 PAYLOAD_TOO_LARGE {max_bytes}`，带 `X-Request-Id`。原有框架层 413 → PAYLOAD_TOO_LARGE 的映射保留。
2. **charset**：新增 `Utf8JSONResponse`（`application/json; charset=utf-8`，契约 §1 的媒体类型）。`error_response` 与 FastAPI `default_response_class` 都用它，/health 也改用它。404/405/413（含分块）/400 校验/400 坏 JSON/500/AppError/admin 404 都有自检。
3. **验证**：API 自检 188/188（+21）；HEAD + 这 6 个文件单独导出验证 188/188；ruff、format、mypy --strict 通过；测试套件 api_app+unit 474 passed / 89 skipped（AIA_CONFIG_DIR 指向仓库或快照都通过）；check_contract 与 check_code_namespaces 通过；plan_yaml_diff 6 个文件 diffs=0；gitleaks 与 scan_licence 未命中。

### 需他人处理（补充）
- **架构师**：把 `ingest.imports` 三个键补进 plan §6.1（或另定文件/键名）。补入后由后端去掉 `config/ingest.yaml` 里的注释。
- **测试**：plan 更新后同步 `config_defaults/ingest.yaml` 快照。
- **运维**：推送 045c550（在 ce38a3f 之后）。nginx 无需改动；若改 `client_max_body_size`，需同步 `ingest.imports.max_request_bytes`。

**补充简报**：通过，提交 045c550；架构师需把 `ingest.imports` 补进 plan §6.1，运维推送。

## 补充（编排者 14:16：304 声明 / ST103，提交 0111b51）

- **改动**：`app/api/v1/meta.py` 给 `GET /meta/enums` 在 OpenAPI 声明 `304`（无 content；headers `ETag`、`Cache-Control`，依契约 §1 / §7.10），200 也声明了这两个头。`app/common/errors.py` 的 405 处理顺带修了一个 T-B03 引入的回归：`/me/profile` 的 GET 和 PUT 分两条路由注册，Starlette 的 `Allow` 只报第一条路由（`GET`），schemathesis 报 ST205。现在用公开的 `route.matches` 按方法逐一试匹配，取同一路径全部路由方法的并集（`GET, PUT`），兼容 FastAPI 0.162 的嵌套 include_router。
- **复现**：测试方的 `tests/backend/contract/test_contract_live.py`（只读 worktree，schemathesis 4.33.0 装在 /tmp，不进项目 venv），起本地 uvicorn，无 DB、无网络（`unshare -rn`，去掉 MAIRUI_LICENCE）。
  - 修复前（HEAD 导出树）跑 seeds 1–15：ST103（`/meta/enums` 304）在 5/15 个种子中出现（seed 1、2、8、14、15）；ST205（`/me/profile`）15/15。
  - 修复后跑 seeds 1–20：**20/20 全通过，0 失败**。
- **自检**：selftest_api 196 PASS（新增 304 声明/行为与 405 Allow 并集断言）；ruff/format/mypy --strict 干净；测试方 api_app+unit 474 passed；CI check_contract / check_code_namespaces 通过；gitleaks + scan_licence 无命中。
- **其他 304 / 未声明码**：目前只有 /meta/enums 会返回 304。全局已声明 `4XX`/`5XX` 统一错误体（契约 §2），413/405/401/503 等都在其内，没有发现别的未声明状态码。
- **需他人处理**
  - 测试：live 契约测试只覆盖 GET，POST/PUT 端点没有被 fuzz；而且测试环境要自备 schemathesis（项目 venv 里没有）。是否纳入 CI，由测试/架构决定。
  - 后续：契约里 /terminal、/today 的弱 ETag/304 还没实现，实现时要同样声明 304，由对应任务负责人处理。
