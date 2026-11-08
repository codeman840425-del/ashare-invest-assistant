# T-T01c 报告：评审 F3 修复与 rebase 到 origin/main

- 角色：测试；工作区 `/workspace/wt-tests-T-T01`，分支 `test/T-T01`
- **只在本地，未推送，也没有交给任何人。** 只改了 `tests/`。没有调用麦蕊或任何真实行情 API。本报告不含任何原始敏感值。
- **最新状态见文末 §6–§12（第二轮，基底 origin/main `0f2e32f`，HEAD `f545a6a`）。** §1–§5 是第一轮记录，其中的提交号、基底与阻塞项已被 §6 起的内容取代。
- 第一轮 HEAD：`235a248`；基底 origin/main 为 `1d2fbda`

## 1. F3（review-T-B02.md）修复：提交 `235a248`（单独提交）
评审指出的问题：4 条配置合并用例用整块 `BUSINESS` 环境变量来测合并规则。plan §6.1 只允许白名单内的环境变量键，后端拒绝整块 `BUSINESS` 是正确行为。**改动全部在测试侧，不需要改任何非 tests 文件。**

**`tests/backend/api_app/test_config.py`**
- 合并规则改为经运行时覆盖层 `Settings.with_business_overrides(runtime)` 测试：
  - `test_runtime_override_deep_merge_keeps_siblings`：只覆盖叶子键，同级键与其他业务文件保留；返回新对象，原 Settings 不变。
  - `test_business_list_replaced_wholesale`：列表整体替换（架构师口径）。
  - `test_business_null_means_not_overridden`：null 视为未覆盖。
  - `test_business_merged_result_validated[unknown-key|wrong-type]`：未知键或类型错误时抛 `ConfigError`，且消息不回显取值（用虚构标记检查）。
- 环境变量层只测 plan §6.1 白名单里的 3 个心跳键，嵌套和扁平两种写法各 3 条（`test_env_whitelisted_heartbeat_keys`，共 6 条）：
  - 覆盖 `business.ingest.heartbeat` 的对应字段，其余心跳键保留；
  - 顶层 `ingest_*` 字段取值一致。
- 新增 `test_env_business_outside_whitelist_rejected`，3 条：
  - 整块 `BUSINESS`；
  - 白名单外的 `BUSINESS__REALTIME__…`；
  - 白名单外的 `BUSINESS__INGEST__HEARTBEAT__INTERVAL_S`。
  - 3 条都应抛 `ConfigError`，且消息不回显取值。
- 后端没有这些能力时（旧后端）skip，原因写明“依赖后端 T-B02（34641ae）”。

**`tests/backend/api_app/conftest.py`**
- `clean_env` 额外清除所有 `BUSINESS__*` 环境变量。

**验证**
- 在评审用的后端 `34641ae`（契约 v0.2.2）上：评审时的 **4 个失败 → 0 个失败**。
- `test_config.py` 单独运行：44 passed，1 xfailed（T-B25）。

## 2. rebase
- `git fetch` 后，origin/main 在任务期间被别人推进了两次：35f0139 → 2dc2f1b → 1d2fbda。我每次都重新 rebase，最终基底为 **`1d2fbda`**。
- 三次 rebase 都**没有冲突**：这段时间 origin/main 没有改过 `tests/`。
- 最终 `origin/main..HEAD` 只含 `tests/` 路径（63 个文件，非 tests 文件为 0）。

| 原提交 | rebase 后 | 说明 |
|---|---|---|
| 3adfeba | `0bf1ceb` | T-T01，已并入扫描修正（见 §4） |
| 23fb8b7 | `c32ef03` | T-T01a |
| d745148 | `fa066f5` | T-T01b，已并入扫描修正（见 §4） |
| 新增 | `235a248` | T-T01c F3 修复 |

## 3. 测试结果（最终 HEAD `235a248`）
| 环境 | 结果 |
|---|---|
| **评审后端 `34641ae`**（契约 v0.2.2 文档 + 后端；live 契约测试用自起的 uvicorn :18080） | **475 passed / 0 failed / 89 skipped / 4 xfailed** |
| **默认环境**（工作区自带 origin/main `1d2fbda` 的 docs、后端和 config，即合入后 CI 会看到的组合） | **470 passed / 4 failed / 89 skipped / 5 xfailed**；4 个失败都来自契约 v0.2.3，见 §5 |
| integration（testcontainers） | 4 passed |
| vitest | 9 passed |
| Playwright（1440×900，端口 4399） | 2 passed，2 skipped |
| `generate.py --check` | **通过**（0 个文件不同） |

xfail 都有原因，都指向 T-B25：llm.yaml、BUSINESS_FILES、llm 模型、api_key_env。默认环境多出 1 个 xfail：`error_codes` 缺 v0.2.3 的 `PAYLOAD_TOO_LARGE`，归后端。

## 4. 扫描（范围：`origin/main..HEAD` 全部 diff）
- 仓库自带的 `scripts/ci/secret_scan.py range origin/main..HEAD`（CI 用的同一套 S1–S9 规则）：
  - 第一次扫出 **3 处阻断**，都是测试里的虚构值，但字面形式触发了规则：
    - `tests/backend/conftest.py` 中 testcontainers 的占位密码，触发 S2；
    - `test_config.py` 中敏感键用例写入的虚构 licence，触发 S1；它在两个提交里出现，计 2 处。
  - 处理：占位密码缩短，虚构 licence 改用下划线分隔，规则不再命中，测试语义不变。修正以 fixup 并入引入它们的 T-T01 和 T-T01b 提交，因为 CI 是逐个提交扫描的；F3 仍是单独提交。
  - 复扫：88 个文件版本，**阻断 0，警告 0**。
- gitleaks（docker，分别用仓库的 `.gitleaks.toml` 和默认规则，`--redact`）：**两次都是 no leaks found**。
- 自查 S1–S9 计数：
  - hex32+ 命中 44 处，都是夹具 sha256（README 和 meta.json 中）；
  - licence 赋值命中 1 处，是 `FAKE_…` 虚构值；
  - 其余为 0。
- 原始样本泄漏扫描：从样本中提取 150 个特征 token，命中 7 个，逐个核对：
  - 4 个是整数阈值（X0000000 形）；
  - 1 个是 YYYYMMDD 日期；
  - 2 个是低熵 8 位串（6 个 0），只是合成 10 位<field:trade-id>的子串，属于偶合。
  - **无原始样本泄漏。**
- 临时脚本和目录已删除。

## 5. 阻塞与后续（按负责人）
- **测试（我）**：需要新任务“测试同步契约 v0.2.3”。origin/main `1d2fbda` 已带 v0.2.3 文档（b864d97、dd24549），默认环境 4 个失败全部来自这里：
  1. `test_snapshot_equals_plan_block[market_rules]`、`[horizon_classifier]`：plan §6.1 的 YAML 块已改（horizon `classifier_version` 1.1.0、`version_no` 2，market_rules 新增键），`config_defaults/` 快照需要同步；
  2. `test_contract_header_version`：契约头已是 v0.2.3；
  3. `test_contract_parsers_sanity`：错误码数 57→58（新增 `PAYLOAD_TOO_LARGE`），`import_status` 枚举也有变化。
  - 这些不属于 F3 范围，本次没改。**不处理的话，合入后 CI 会红。** 请批准后我按 T-T01d 处理。
- **后端**：按 review-T-B02 §4 同步 v0.2.3：
  - `CONTRACT_VERSION` 改为 v0.2.3；
  - 新增错误码 `PAYLOAD_TOO_LARGE`；
  - market_rules 的 `limit_order_only_exchanges` 与 `applies_to_boards`；
  - horizon 1.1.0；
  - 迁移 0003。
  - 另有 F5、F6；T-B25 做 llm.yaml，并按 `*_env` 约定修 F4。
- **运维**：review-T-B02 中的 F1、F2 看上去已由 `2dc2f1b` 处理，待评审确认；m6（X-Request-Id）仍未修。
- **用户/负责人**：推送 `test/T-T01`、开 PR 合入 main 需要用户批准。合入后 M9 关闭，但应先完成上面的 v0.2.3 测试同步。


---

# 第二轮（父任务追加要求 13:55 / 14:05，均为 America/Denver 时间）

## 6. 结论
- **新 HEAD：`f545a6a`**，基底 **origin/main `0f2e32f`**（任务中 origin/main 从 37d454b 又推进到 0f2e32f，后者只改 CI 的 secret_scan / .gitleaksignore / CODEOWNERS，rebase 无冲突）。`origin/main..HEAD` 只含 `tests/`（非 tests 文件 0 个）。**只在本地，未推送，未交给任何人。**
- CI 中归测试的红项已全部清掉；剩余红项不在 tests/ 内（见 §11）。

## 7. rebase 后提交（自底向上）
| 提交 | 内容 |
|---|---|
| `b8f5579` | T-T01 脚手架 |
| `e9c7665` | T-T01a |
| `5b47b84` | T-T01b |
| `b862418` | **F3 修复（单独提交）** |
| `c5d320c` | CI 夹具格式：meta.json `fake_identifiers` 改为扁平字符串列表（明细移到 `fake_identifiers_detail`）；expected.json 的 HTTP 错误改记 `http_error`，只保留 §4.1 导入码 |
| `9d897de` | 同步 plan/契约 v0.2.3：market_rules / horizon_classifier 快照、`/meta/enums` 版本、`PAYLOAD_TOO_LARGE` |
| `cbaa732` | 用例 E：novice 的 short 封顶 59（SH0C），suitable 为 [] |
| `465abbc` | app.db 元数据约定单元测试（schema、`pk_<表>`、timestamptz、numeric(20,4)、命名 CHECK、PG DDL 编译）；CI 后端作业覆盖率 78.9% → 91.0% |
| `de4bd50` | 同步 IT0C：horizon 快照加 IT0C；novice / 未填经验时 intraday_t 也封顶 59（caps `IT0C`），由 strict xfail 转为正式断言 |
| `f545a6a` | 网关 / 后端 live 用例（§9） |

## 8. 父任务 (a)–(f)
- (a) S2（`tests/backend/conftest.py:61` 占位口令）、S1（`test_config.py:226` 虚构 licence）改为不触发规则的假值；`secret_scan range` 阻断 0。
- (b) fmt_a 两个脱敏主样本需登记到仓库根 `.secretscan-allow.yaml`，**该文件不在 tests/，我没改**，条目见 §10，交运维。
- (c)(d) meta.json `fake_identifiers` 与 expected.json 已按 `scripts/ci/check_fixtures.py` 的格式调整；`generate.py --check` 0 个文件不同，20 个文件可复现。
- (e) 契约 §4.1 的 46 个码全部覆盖（check_fixtures ③ OK）。
- (f) 用例 E：novice 时 short 封顶 59、suitable []；intraday_t 同样封顶 59（后端 IT0C 已落地，正式断言通过）。

## 9. 栈与 live 契约测试
- 按要求从 rebase 后的工作区（origin/main 检出，未改 deploy/）执行 `deploy/scripts/up.sh`：postgres、redis、migrate（退出 0）、timescale-apply（退出 0）、api、worker、beat、ingest、signal-rt、nginx 全部 healthy。
- **`/meta/enums` 实际返回 `v0.2.3`**，不是父任务说的 v0.2.2。这与契约文档 v0.2.3、后端 `app/schemas/enums.py` 一致，判断为父任务的预期写旧了，不是缺陷。
- 新增 `tests/backend/contract/test_gateway_live.py`（标记 contract；`AIA_CONTRACT_BASE_URL` 指定目标，默认 8080；服务不可达时整体 skip，所以 CI 后端作业里是 skip）：
  - `/api/v1/health/live` 200；网关自身 `/healthz` 返回 ok（仅网关）。说明：nginx 根路径 `/health/live` 会落到占位页 `location /` 并返回 200，不是健康检查，所以没用它断言。
  - 客户端合法 `X-Request-Id` 在成功响应头和 404 错误信封 `error.request_id` 中原样保留；非法值（含空格、129 字符、含斜杠）和缺失时，生成 `req_` + 32 位 hex，且响应头与信封一致。
  - 405（`DELETE /api/v1/health`）：带 `Allow`（含 GET），信封码 `METHOD_NOT_ALLOWED`，`details.allowed` 与 Allow 一致；`/admin` 用错方法返回 404 且无 Allow。
  - 413（仅网关）：只发头部，`Content-Length` = 26 MiB + 1，`POST /api/v1/imports` → 413，JSON 信封，码 `PAYLOAD_TOO_LARGE`，`max_bytes` = 27262976，request_id 规则同上（有 / 无客户端 ID 两种）。
- 结果（tests/backend/contract 整个目录）：

| 目标 | 结果 |
|---|---|
| nginx `<url>` | 16 passed（含 schemathesis 6 个子测试） |
| 直连后端 `<url>` | 13 passed，3 skipped（`/healthz` 与 2 个 413 仅网关适用） |

- **发现（归后端）**：schemathesis 偶发 `ST103 Undocumented status code`：`GET /api/v1/meta/enums` 带 `If-None-Match: *` 时返回 304，而 OpenAPI 只声明 200 / 4XX / 5XX。契约 §/meta/enums 明确要求支持 304，所以行为正确，**缺的是 OpenAPI 声明**：请后端在 `app/api/v1/meta.py` 的路由上加 `responses={304: {"description": "Not Modified"}}`（`/terminal`、`/today` 落地时同理）。pytest live 用例是随机生成，约 1/6 的运行会撞到；CI contract 作业用固定 seed `20261101`，我用同版本 schemathesis 4.33.0 和同样参数，对一次性 uvicorn + 独立 postgres/redis 复现，结果通过（90/90），另试 5 个 seed 也没撞到。所以**不影响 CI 变绿，但这是潜在隐患**。我没有在测试里屏蔽它。

## 10. 交运维：`.secretscan-allow.yaml` 条目（追加到 `entries:` 下）
```yaml
  - rule: '*'
    origin: desensitized_main
    path: tests/fixtures/broker_statements/fmt_a/positions_sample.txt
    sha256: 5804c01dddc93b884aee38296c3ce47f13cd4d14d5f9dac25d86caac9e924343
    reviewer: <评审人>
    reason: 人工脱敏主样本（generate.py 生成，T-T01a）
    added_by: <登记人>
    added_at: <YYYY-MM-DD>
  - rule: '*'
    origin: desensitized_main
    path: tests/fixtures/broker_statements/fmt_a/trades_sample.txt
    sha256: f<account>cb65ba3120399fd9b4cd73bea97de564db66e08db7bf5fa
    reviewer: <评审人>
    reason: 人工脱敏主样本（generate.py 生成，T-T01a）
    added_by: <登记人>
    added_at: <YYYY-MM-DD>
```
- sha256 已在最终 HEAD 上复核。在临时副本里加入这两条后：`check_fixtures` 0 个失败，`scripts/ci/tests` 90 passed / 36 skipped。

## 11. 测试结果与 CI 判断（最终 HEAD `f545a6a`）
| 项 | 结果 |
|---|---|
| CI backend 作业模拟（git archive + `uv sync --frozen` + `--cov-fail-under=80` + `check_coverage.py`） | **500 passed / 0 failed / 102 skipped**，覆盖率 **91.0%**，check_coverage 通过 |
| 工作区 pytest（tests/backend + tests/replay，栈在线） | 504 passed / 90 skipped；偶发 1 个子测试失败，即 §9 的 304 问题 |
| contract 作业静态部分（check_contract 文档 + `--meta-json`、check_code_namespaces 两次） | 全部通过 |
| contract 作业 schemathesis（CI 同参数，一次性环境） | 90/90 通过 |
| vitest | 9 passed |
| Playwright | 2 passed，2 skipped |
| `generate.py --check` | 0 个文件不同 |
| `check_fixtures.py`（仓库原样） | 2 个失败，都是条件 4，即 §10 的登记，需运维处理；46 码覆盖 OK |
| `scripts/ci/tests` | 90 passed，36 skipped |

**CI 判断**
- **backend**：绿。
- **contract**：绿。
- **secret-scan / gitleaks**：
  - `secret_scan range origin/main..HEAD`：阻断 0，警告 0；
  - `tree`：阻断 0，警告 0（probes S1 已由 0f2e32f 的指纹豁免消除）；
  - `history`：阻断 0，警告 1（S9，前端 prototype/dist，归前端）；
  - gitleaks 8.30.1（`--ignore-gitleaks-allow`，range 与 `--all`）：命中 0。
  - 本作业中只有 **check_fixtures 条件 4 是红的**，等运维登记 §10 的条目。
- **fixtures**：同上，只剩条件 4 → 运维。
- **frontend**：不归测试（锁文件、prototype/dist），见 T-O02。

## 12. 原始样本泄漏扫描（`origin/main..HEAD` 新增行，utf-8 与 gbk 两种解码，只看计数）
- 从样本提取 150 个特征 token、71 个长行。
- 命中 1 个 token、1 个长行，逐个核对：
  - token 是 plan §6.1 原文里的整数阈值（horizon 配置快照）；
  - 另一 token 命中是合法的 YYYYMMDD 日期，出现在 `trades_cr.txt`；
  - 长行是样本的列表头行（不含数字，只是格式结构），出现在 CR 换行变体夹具中，T-T01a 起就存在。
- **无原始样本泄漏。** 临时脚本已删除。

## 13. 阻塞（按负责人）与环境状态
- **运维 + 评审人**：把 §10 的两条加入 `.secretscan-allow.yaml`，填评审人、登记人、日期。这是 fixtures 与 secret-scan 作业剩下的唯一红项。
- **后端**：给 `GET /meta/enums` 的 OpenAPI 声明 304（§9）。
- **前端**：prototype/dist 的 S9 警告（history 扫描，非阻断）。
- **用户**：推送 `test/T-T01`、开 PR 需要用户本人批准。
- **栈状态**：开始时只有 aia-postgres-1、aia-redis-1 在运行；现在 **aia 全栈（api / worker / beat / ingest / signal-rt / nginx / postgres / redis）仍在运行**。postgres 是从工作区 compose 路径重建的，数据卷保留。如需恢复原状，在工作区执行 `docker compose -p aia stop api worker beat ingest signal-rt nginx`。我自己起的一次性容器（契约复现用的 db/redis、遗留的 testcontainers）都已删除；没有动 ci-drill-* 容器。
