# T-live-83a031c：aia-t01（83a031c / 迁移 0016）实机复测报告

- 测试员：测试；执行时间：2026-11-02 10:15–10:35（Asia/Shanghai）＝ 2026-11-01 19:15–19:35（MST）
- 环境：aia-t01 compose（工作目录 /workspace/aia-t01-deploy-o11/deploy/compose），部署树 HEAD `eb89502`（含 `83a031c` T-B10），api 镜像 `sha256:2a9b079acce8…`；9 个服务全部 healthy；`/healthz`、`/health/ready` 均 200
- 测试代码：worktree `test/T-T01` 已提交 HEAD `e5fb12c`，经 `git archive` 导出到 /tmp/tlive/h2 运行（未改 tests/、未提交、未推送）；docs/config 软链到部署树
- 凭据：只经 python-dotenv 读入进程内存；日志、报告未出现密码/令牌/cookie（已程序化核对，见 §6）
- 对比基线：T-live-0f8129b

## 1. 结论一览

| 部分 | 通过 | 失败 | xfail | 其他 | 相比 0f8129b |
|---|---|---|---|---|---|
| ① 实机契约（schemathesis + 网关 + 登出态冒烟），tests/backend/contract | 49（另 19 个子测试通过） | 4 | 0 | — | 失败 2→4，根因变了（见 F-1） |
| ① 进程内 meta / 迁移 head：test_meta_enums.py + test_alembic_head_is_known | 24 | 0 | 0 | — | meta 枚举 xfail → 通过 |
| ② /candidates 进程内用例：test_contract_t_a11_t_f22.py | 25 | 0 | 1 | — | 原 16 个 xfail（未挂载）→ 通过 |
| ② T-T16 / T-O11 裁定：test_rulings_t_o11_t_t25e.py | 12 | 0 | 14 | — | 新文件 |
| ②（附带）test_contract_v028_t_t23.py | 31 | 0 | 5 | 跳过 2 | 新跑 |
| ② /candidates 实机登录检查（/tmp/tlive/live_auth.py） | 20 | 0 | — | — | 新增（上次没有账号） |
| ③ 登录上传 trades_sample.txt | — | — | — | **未执行** | 仍未执行，原因变了（见 G-1） |

- 迁移 head：库内 `alembic_version` = **0016** ✅；已提交的 KNOWN_HEADS（e5fb12c）已含 0015、0016，`test_alembic_head_is_known` 通过。
- 三个枚举：`/meta/enums`（v0.2.9，共 81 个，上次 78 个）已包含 ✅
  - `candidate_decision` = continue / watch / drop
  - `research_candidate_origin` = strategy_screen / suggestion / manual / from_stock
  - `research_candidate_status` = researching / watching / dropped / planned
- 414：**已不是 HTML** ✅。现在返回 `414 application/json`，信封为 `{"error":{"code":"URI_TOO_LONG",…,"request_id":…}}`，并带 `X-Request-Id`，与 body 一致（运维 c0388f8）。

## 2. ① 实机契约 —— 4 个失败，根因相同

命令：`AIA_CONTRACT_BASE_URL=<url> pytest tests/backend/contract`，日志在 /tmp/tlive/r2_contract.log 和 .xml。

失败的端点：GET /accounts、/imports/{batch_id}/rows、/trades、/candidates/{candidate_id}/versions。schemathesis 随机生成超长 URL，所以每次落到的端点不同。

- **F-1（新根因；负责人：后端，契约由架构师确认）**：nginx 的 414 已改成 JSON，但 OpenAPI 的 `components/schemas/ErrorCode` 枚举里没有 `URI_TOO_LONG`，docs/api-contract.md 也查不到 `URI_TOO_LONG`/414。因此 schemathesis 报两项：
  1. `JsonSchemaError`：返回内容不符合 `4XX` 的响应 schema；
  2. `AcceptedNegativeData`：414 不在预期状态码列表里。

  修法（二选一）：
  - 契约和 OpenAPI 把 `URI_TOO_LONG` 加进 ErrorCode，并声明 414；
  - 或者 nginx 改用契约里已有的错误码。

  **上次**（0f8129b）的 2 个失败是 nginx 返回 HTML 414（运维），这一项**已修好**。

## 3. ② /candidates

### 3.1 进程内（部署树后端代码 + 一次性 testcontainers PG/Redis，不碰 be-b03a-pg）
- test_contract_t_a11_t_f22.py：25 通过、1 xfail。唯一的 xfail 是 `test_a11_11_no_notifications_no_plans` 的 SSE 部分，原因是 /stream 未挂载（后端 T-B05）。上次 16 个“/candidates 未挂载 + F22”的 xfail 全部转为通过。
- test_rulings_t_o11_t_t25e.py：12 通过、14 xfail，xfail 全部是后端缺口：
  - `test_t16_db_rejects_candidate_snapshot_without_user` 和 `test_t16_writer_asserts_user_id`：T-O11 裁定 D，candidate 快照的 user_id 必填 CHECK 和写入断言还没做（**后端**）；
  - 12 个 `test_etf_without_data_source_always_t_plus_1[*]`：T-B47-R10（**后端**）。
- 首次运行时该文件有 9 个失败，都是 `FileNotFoundError: <导出根>/config/market_rules.yaml`：测试按仓库相对路径读 config，没有读 `AIA_CONFIG_DIR`。软链 config 后重跑全部正常（G-3，测试）。

### 3.2 实机登录检查（测试账号，CSRF 双提交）—— 20/20 通过
- 未登录访问 GET /candidates 返回 401 AUTH_REQUIRED。
- 登录：POST /auth/login 返回 200，下发 `sid` 和 `csrf_token` 两个 cookie，body 里的 csrf_token 与 cookie 一致，X-Request-Id 格式正确。
- 写请求不带 X-CSRF-Token 时返回 403 CSRF_FAILED，没有建出数据。
- 列表：GET /candidates 和 `?status=all` 返回 200，信封为 `{items, next_cursor}`，条数为 0（该用户没有候选）。`?status=bogus` 返回 400 VALIDATION_ERROR。
- 隔离 / 不存在：对随机 UUID 调 GET /candidates/{id}、/versions、/versions/1，以及带合法 body 的 POST /candidates/{id}/versions，全部返回 404 NOT_FOUND，并带 request_id。/candidates/not-a-uuid 返回 400。
- 不可变：PUT、PATCH、DELETE /candidates/{id} 返回 405，`Allow: GET`。
- 登出：返回 204，之后再访问返回 401。
- **局限（G-2）**：
  - 实机没有用真实候选验证详情，也没做两个用户互访。原因一是实机只有 1 个测试用户，而规定不准新建账号；原因二是契约规定候选不可删除（DELETE 返回 405），建出来就清不掉。
  - 他人 id 返回 404、列表只含本人数据，这两点已由进程内 T-A11 用例（验收 2）覆盖并通过。
  - 如需在实机验证，需要第二个测试账号，或者批准在 aia-t01 留下一条无法删除的测试候选（运维/PM 决定）。

## 4. ③ 登录上传 —— 未执行

- **G-1（新原因；负责人：运维，或由 PM 决定）**：测试账号名下**没有券商账户**（GET /accounts 返回 n=0；只读查库 `app.accounts` 也是 0）。POST /imports 必须带本人的 `account_id`；而 API 只有 `POST /accounts`，没有删除或归档接口，建出来的账户无法通过正常 API 清掉。
  - 按“不要新建任何账号”和“测试数据须经正常 API 清理”两条规则，我停在建账户之前，没有上传。
  - **上次**的原因是没有测试用户（users=0）；**现在**已有用户（users=1），这一项已解决。
  - 解法（二选一）：运维给 aia-t01 测试用户预置一个券商账户；或者 PM/用户明确批准我经 `POST /accounts` 建一个测试账户，并接受它留在库里。
- 已做的无副作用验证：用随机 account_id 上传 trades_sample.txt，CSRF 通过后返回 404 NOT_FOUND，带 request_id，没有建出批次。这说明登录、CSRF 双提交、multipart 链路和归属校验都正常。
- 期望结果（来自 fmt_a/expected.json，留待执行）：
  - parser `tdx_trades_v1`，编码 gbk，状态 `previewed`；
  - ok 55、warning 11（4 个 IMPORT_MISSING_OPENING_POSITION、7 个 IMPORT_CASH_CHAIN_BREAK）、error 0、skipped 0，共 66 行；
  - 上传返回 201、状态 `uploaded`，后台解析后轮询 GET /imports/{id} 应变为 `previewed`；之后 POST /imports/{id}/discard。

## 5. 清理与数据状态
- 只读查库（执行后）：`app.research_candidates` 0、`app.import_batches` 0、`app.accounts` 0、`app.users` 1。本轮**没有留下任何测试数据**，不需要清理。
- 会话：第一次运行脚本时，我自己的脚本 bug（CSRF cookie 名写错）导致登出返回 403，留下 1 个登录会话。它会按会话 TTL 自然过期，没有其他影响。后两次运行均正常登出。

## 6. 缺口与负责人汇总

| 编号 | 内容 | 负责人 | 相比 0f8129b |
|---|---|---|---|
| F-1 | 414 的 `URI_TOO_LONG` 不在 OpenAPI/契约的 ErrorCode 里，414 也未声明，导致实机契约 4 个失败 | 后端（架构师确认契约） | 原 HTML 414（运维）已修，根因变为此项 |
| G-1 | 测试用户没有券商账户，上传没法做；账户无删除 API | 运维 / PM | 原“无测试用户”已解决，变为此项 |
| G-2 | 实机没法做跨用户隔离和真实候选详情（只有 1 个用户，候选不可删） | 运维 / PM | 新 |
| G-3 | test_rulings_t_o11_t_t25e 按仓库相对路径读 config/market_rules.yaml，忽略 AIA_CONFIG_DIR | 测试 | 新 |
| G-4 | T-O11 裁定 D：candidate 快照 user_id 必填 CHECK 和写入断言（2 个 xfail） | 后端 | 新 |
| G-5 | T-B47-R10：ETF 无 data_source 一律 T+1（12 个 xfail） | 后端 | 新 |
| G-6 | /stream SSE 未挂载（T-A11 验收 11 的 SSE 部分，1 个 xfail） | 后端 T-B05 | 上次在 F22 xfail 集合里 |
| — | 三个枚举缺失 | 后端 | **已修** |
| — | /candidates* 未挂载、F22 | 后端 | **已修** |
| — | migration head / KNOWN_HEADS | — | 0016，已提交的 KNOWN_HEADS 已含，正常 |
| 备注 | 测试用户名出现在运维报告 /workspace/team/reports/T-O11.md 里（密码没有）；本轮日志和报告经程序化核对无凭据值 | 运维（可选脱敏） | 新 |

## 7. 产物
- /tmp/tlive/r2_contract.log、.xml：实机契约
- /tmp/tlive/r2_inproc.log、.xml：进程内首跑（含 G-3 的 9 个失败）
- /tmp/tlive/r2_rulings.log、.xml：软链 config 后重跑
- /tmp/tlive/live_auth.py；live_auth3.log 为正式结果，live_auth.log 和 live_auth2.log 是脚本修正前的运行

---

## 8. 补充：登录上传复测 + 跨用户隔离（编排者裁定后，2026-11-02 10:24–10:33 Asia/Shanghai ＝ 2026-11-01 19:24–19:33 MST）

### 8.0 过程说明
- 第一次运行时，login 返回 **502**。nginx 日志为 `api could not be resolved`，原因是运维在部署 dcf3cfc（nginx 断开外部 DNS），api 容器正在重建。这次没有任何写入。
- 之后用 /tmp/tlive/mon3.sh 等待：每 30 s 检查一次 healthz、ready、enums 和 api 容器 health，要求连续 2 分钟健康。19:29:05 MST 达到稳定。
- 稳定后的正式运行（/tmp/tlive/live_upload_iso.py，日志 live_upload_iso.log；补测 iso_fix.log）中，**没有遇到 502，也没有触发重试**。
- 凭据只经 python-dotenv 读入进程内存（aia-t01.env 为用户 A、aia-t01-user2.env 为用户 B）。没有新建用户；券商账户只建了 1 个。

### 8.1 券商账户
- 建账户前，A 名下没有任何账户，也没有名称含 test 的账户。于是经 `POST /accounts` 建了**1 个**账户：alias `test-fmt_a-upload`，broker_name `test-broker`，带 Idempotency-Key，返回 **201**，X-Request-Id 合规。
- 账户 id：**`<agent:已脱敏>`**。按要求保留。
- 该接口只有 alias 和 broker_name 两个字段，**没有账户号或<account-field>字段**，因此没有提交任何账号类数据。返回的 `shareholder_code_masked` 和 `fund_account_masked` 都是 null。

### 8.2 上传结果（A 用户，CSRF 双提交）

| 文件 | POST /imports | 预览状态 | stats（ok/warning/error/skipped，rows） | parser / 编码 | file_findings | 逐行 rows | normalized |
|---|---|---|---|---|---|---|---|
| trades_sample.txt（kind=trades），batch `<agent:已脱敏>` | **201 uploaded**，X-Request-Id `req_734549500b12e694fcd83e1dde70bf4d` 合规 | **previewed**（约 2 s） | **55 / 11 / 0 / 0，rows 66**（new 66） ✅ | tdx_trades_v1 / gbk ✅ | [] ✅ | 11 行 warning 的行号、codes（4 个 IMPORT_MISSING_OPENING_POSITION、7 个 IMPORT_CASH_CHAIN_BREAK）、dedup_status=new 全部一致；其余 55 行均为 ok ✅ | 14 个字段中 12 个一致；**2 个不一致**，见 D-1 |
| positions_sample.txt（kind=positions），batch `<agent:已脱敏>` | **201 uploaded**，X-Request-Id `req_c2d45f61e4dd053740f560462faa4c4c` 合规 | **previewed** | **1 / 0 / 0 / 0，rows 1** ✅（另有 needs_action_open=1） | tdx_positions_v1 / gbk ✅ | IMPORT_SNAPSHOT_AS_OF_ASSUMED、IMPORT_SNAPSHOT_TOTALS_MISMATCH ✅ | 第 5 行 ok，kind=snapshot_position ✅ | 4 个字段中 3 个一致；**1 个不一致**，见 D-1 |

- **D-1（负责人：测试，fixture 过时）**：normalized 里的 `security_code`，实际返回带交易所后缀，expected.json 写的是 6 位代码：
  - 实际值：`600001.SH`、`301002.SZ`、`002001.SZ`；
  - expected.json：`600001`、`301002`、`002001`。

  契约 §证券代码 规定格式为 `{6位代码}.{SH|SZ|BJ}`，所以**后端符合契约**，应更新 fmt_a/expected.json（以及 generate.py）的 normalized 期望值。其余 normalized 字段（qty、price、amount、net_amount、cost_price、market_value、日期、时间、side 等）全部一致。

### 8.3 清理
- 两个批次都由 A 经 `POST /imports/{id}/discard` 处理，返回 **200 discarded**；之后 GET 两个批次，状态都是 discarded。
- 只读查库：
  - `import_batches` 2 条，都是 `discarded`；
  - `trades` 0、`account_events` 0、`broker_position_snapshots` 0、`broker_position_snapshot_items` 0、`opening_positions` 0，即**没有写入任何成交或持仓**；
  - `accounts` 1（保留）。
- `import_rows` 还剩 67 行，属于两个已作废批次，是作废后保留的预览行。discard 只把批次和文件标记为作废、删除原始文件，不删预览行，属于设计行为。如果要求作废后清除预览行，需要后端或架构师确认保留策略。
- A、B 都已登出：返回 204，之后再访问返回 401。

### 8.4 跨用户隔离（A=user1，B=user2）
- 数据清单：A 有 1 个账户、2 个批次（隔离检查期间保持 previewed，检查结束立即作废），候选 0、成交 0。B 的账户、批次、候选、成交都是 0。
- 因为候选不可删除，规定也不准新建，A 的候选和成交没有真实 id 可测，只能按指示用账户和导入批次来测；对随机 id 返回 404 已在 §3.2 覆盖。
- **B 访问 A 的资源（共 25 项，含补测）**：

| 检查 | 结果 |
|---|---|
| GET /imports/{A 批次}、/rows、/errors.csv（2 个批次） | 404 NOT_FOUND ✅ |
| PUT /imports/{A 批次}/options、POST discard、revert、confirm、findings/{id}/resolve（2 个批次；resolve 首次用的 `{}` body 被 400 拦截，属于 body 校验先行；改用合法 body 补测） | 全部 404 ✅；A 的批次状态没有被改动（仍为 previewed） ✅ |
| POST /imports，account_id 用 A 的账户 | 404，没有建出批次 ✅ |
| GET /portfolio?account_id=A 的账户 | 404 ✅ |
| **GET /imports?account_id=A 的账户** | **200，items 为空** ❌，契约要求 404（G-7） |
| **GET /trades?account_id=A 的账户** | **200，items 为空** ❌，契约要求 404（G-7） |
| B 的列表 /accounts、/imports、/trades?include_voided=true、/candidates?status=all、/portfolio 中是否出现 A 的 id | 都没有出现 ✅ |

- **A 访问 B 的资源（反向）**：B 没有任何资源，只能检查 A 的列表 /accounts（1 条）、/imports（2 条）、/trades、/candidates、/portfolio 里不含 B 的 id，结果都不含 ✅。完整的反向 id 互访需要 B 有数据；规定不准再建券商账户，所以没做（G-2 仍有部分缺口）。
- **G-7（新；负责人：后端）**：契约 §/imports 和 §/trades（v0.2.9 内 T-B46 裁定）都规定：`account_id` 不是本人账户时返回 `404 NOT_FOUND`。后端实际按 user_id 过滤后返回 200 和空列表。**没有数据泄露**，但不符合契约，也让人能够区分账户是否存在的行为与契约不一致。应在 list_imports 和 list_trades 里对 account_id 调用 owned_account 校验。
- 计数：隔离部分正式加补测共 **31 项通过、2 项失败（G-7）**（B→A 25 项中 23 过 2 失败；A→B 列表 5 项过；A 批次未被改动 2 项过；A、B 为不同用户 1 项过）；首次 resolve 的 2 项是测试 body 无效，补测后通过，不计入失败。

### 8.5 本节汇总
- 上传：trades 和 positions 都是 201 → previewed，行数与 expected.json 完全一致。唯一差异是 normalized 的 `security_code` 带后缀（fixture 过时，负责人：测试）。
- 清理：两个批次都已 discarded，没有写入成交或持仓；保留 1 个测试账户。
- 新缺口：G-7（后端）、D-1（测试）。
- 本节日志、报告经程序化核对，不含两个账号的用户名或密码。
