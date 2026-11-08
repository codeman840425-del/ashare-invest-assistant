# 评审报告：T-B02a 补充 / T-B03b / T-B03a / T-B16 / T-B16b / T-B04a-env / T-B45 + T-B04a（后端）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 仓库：`/workspace/ashare-invest-assistant`，后端 `src/backend`
- 依据：`docs/api-contract.md` v0.2.6、`docs/plan.md`；各提交自报（`reports/T-B03a.md`、`T-B03b.md`、`T-B16.md`、`T-B16b.md`、`T-B04a-env.md`、`T-B04a.md`、`T-B45.md`）；上轮评审 `review-T-B02.md`、`review-T-B02a.md`、`review-T-B03.md`
- 范围（按时间）：0111b51 → 48b6686 → a250379 → 21cf382 → 4162abb → 57b1c3b → 38ed2b5 → bc0b3d8 → efcd244（HEAD）
- 只读代码，没有改代码、没有提交、没有推送。下文行号都以 **efcd244 的 `git archive` 导出**为准。

## 0. 检查方式与偏差说明

- 后端用 **uv**（`src/backend/uv.lock`），不是 npm，`npm ci` 不适用。改为：`git archive efcd244` 导出到 `/tmp/rev-be`，在导出目录里执行 `uv sync --frozen`（不改 lockfile），主工作树不动。
- **main 上没有后端测试目录**（测试在测试分支）。所以把测试分支 aca3c34 的 `tests/`（含 `tests/fixtures`）`git archive` 到同一导出目录后再跑。efcd244 自带的 `tests/fixtures` 比 aca3c34 旧，混用时会出现 `expected.json` 缺失和 `KeyError: 'fake_identifiers_detail'` 这类收集错误，所以 fixtures 也换成了 aca3c34 的版本。
- 本机有 PostgreSQL 和 Redis，DB 和接口测试真实运行了。

| 检查 | 结果 |
|---|---|
| `uv sync --frozen` | 通过 |
| `ruff check .` | 通过（0） |
| `mypy`（strict，56 个文件） | 通过（0） |
| `python scripts/ci/check_contract.py` | **失败**：“§6.1 原因码应为 23 个……实际 22”（见 M6 和裁定 b） |
| pytest（`tests/backend` + `tests/replay`，默认环境） | 3 failed / 725 passed / 92 skipped / 21 xfailed / 12 xpassed；覆盖率 86% |
| pytest（证书两组测试，配了临时公钥 + `--runxfail`） | 63 passed / 8 failed（逐条分析见 §5） |

默认环境下的 3 个失败都是**测试分支落后于代码**，不是后端缺陷：
- `test_alembic_head_is_known`：测试仍期望 head 为 0006，代码已到 0007。
- `test_login_success_…`、`test_me_shape`：测试的 Me 字段白名单里没有 `data_licence_status`，但契约 v0.2.6 变更表第 4 项（contract:19）已经要求 `Me` 加这个字段。

默认环境下证书测试大多是 xfail，原因是没有配 `DATA_LICENCE_SEAL_PUBLIC_KEYS`，PUT 返回 `503 MAINTENANCE`（service.py:143，设计如此）。配上临时 X25519 公钥后，生命周期、不回显、IN_USE、DELETE 后可再设、10/h 和 5/h 限速、去首尾空白、长度边界都通过。

自报的“530 passed / 240 skipped / 1 xpassed”与本次数字不同，原因是测试分支版本不同，自报所用的测试版本已无法复现。**建议**：把测试分支合进 main，或者在 CI 里固定测试版本。

覆盖率偏低的模块：
- `licences/service.py` 46%：PUT/DELETE/PATCH 主体只在配了公钥时才执行。
- `licences/hpke.py` 47%：**没有解封（open）往返测试，也没有 RFC 9180 已知答案测试**。
- `licences/keys.py` 46%。
- `auth/deps.py:101-106`：XFF/X-Real-IP 分支没有被测到，即 M1 的修复点没有测试。

## 1. 结论

| 提交 | 任务 | 结论 | 说明 |
|---|---|---|---|
| 0111b51 | T-B02a 补充 | **通过** | `/meta/enums` 在 OpenAPI 里声明了 304 和 ETag/Cache-Control 头；405 的 `Allow` 取同一路径所有路由方法的并集（errors.py `_allowed_methods`），修掉了 ST205；非管理员访问 `/admin/*` 时仍返回 404 |
| 48b6686 | T-B03b（缩减） | **通过** | auth.yaml 和 imports.yaml 落地；会话绝对期限做好了，T-B03 的 **M4 已修复**；改密后吊销全部会话并换发 sid 和 CSRF；Secure 只在非 local 环境开启 |
| a250379 | T-B03b 可信代理 | **通过** | 只采信 `TRUSTED_PROXIES` 里的对端，XFF 只取最右一跳，否则用 X-Real-IP，再否则用对端地址；配合 nginx 的 `X-Real-IP $remote_addr`，T-B03 的 **M1 已修复**。附 m3、m4 |
| 21cf382 | T-B03b enums v0.2.4 | **通过** | 已被 4162abb 和 efcd244 覆盖，没有遗留问题 |
| 4162abb | T-B16（契约 v0.2.5 减法） | **通过** | 同意、风险测评、fit_ack 和 3 个错误码/原因码删干净了。迁移 0005 先守卫（库里还有 `PROFILE_OR_CONSENT_MISSING` 时明确失败），再收紧 CHECK 到 22 个；删 consents 表符合契约表 A 的“已建的由新迁移删除”。T-B03 的 M2、M3 随 v0.2.5 失效 |
| 57b1c3b | T-B03a 防滥用 | **有条件通过** | 注册按 IP 限速、pending 上限、登录限速和渐进锁定都做得扎实（不存在的用户名走同样规则，锁定时不跑 argon2）；条件：修复 **M5**（改密限速在校验之后，可以无限猜旧密码） |
| 38ed2b5 | T-B16b HorizonCap.kind | **通过** | 迁移 0006 的守卫是双向的（升级时遇到 `requires` 失败，降级时遇到 `gate` 失败）；CHECK 要求 `gate` 只配 `HG1–6` 且 `inputs_missing` 为空，与契约一致 |
| bc0b3d8 | T-B04a-env | **通过** | ingest 发现 `MAIRUI_LICENCE` 非空时以 78 退出，符合 plan §2.1B-7 |
| efcd244 | T-B45 + T-B04a | **有条件通过** | 接口层做得好：只有公钥加密、不回显、HMAC 防一证多用、视图不含密文、事件只追加、私钥在 api 进程中存在就拒绝启动。条件：修 **M1**（DELETE 后再 PUT 绕过管理员暂停）、**M2**（重新 PUT 会清掉 quota_exceeded / ip_limited）、**M3**（缺 DB 角色列权限，验收 766 不满足）。M4 的 ingest 调度部分按 T-B04a-x 跟踪，不阻断本提交 |

总体：本批**没有 B 级问题**。

## 2. 上轮 T-B03 问题复核

| 编号 | 状态 | 依据 |
|---|---|---|
| M1 来源 IP 可伪造 | **已修复** | auth/deps.py:90-106（只信可信代理，XFF 取最右一跳）+ deploy nginx.conf（`X-Real-IP $remote_addr`、`X-Forwarded-For $proxy_add_x_forwarded_for`）；缺测试，见 m3 |
| M2 / M3（同意相关） | **失效** | 契约 v0.2.5 删除了同意和风险测评（contract:42、58），4162abb 已删 |
| M4 会话无绝对期限 | **已修复** | auth/sessions.py：TTL = min(idle, 剩余绝对期限)，超过绝对期限即删除；Store 构造时校验 idle ≤ absolute |
| S4 改密吊销会话 | 已做 | api/v1/auth.py 改密分支吊销全部会话并换发 |
| S5 | 未做 | 仍待办，不影响本批结论 |

## 3. 问题清单

### B（阻断）

无。

### M（必须修，合并前或紧接着修）

**M1　DELETE 后再 PUT 可以绕过管理员暂停（efcd244）**
- 位置：`app/licences/service.py:189-200`（`carry_pause = old is not None and old.status == S.PAUSED_BY_ADMIN`）、`:260-280`（`delete_licence` 只做软删除，不保留暂停）。
- 原因：暂停状态只记在当前活行上。用户先 DELETE，旧行软删除，`live_row` 返回 None；再 PUT 时 `carry_pause=False`，新行变成 `pending_verification` 并投递一次验证。管理员暂停就这样被用户自己解除了。直接重新 PUT 时暂停会延续，说明设计本意是“只有管理员能解除”，DELETE 路径漏掉了。
- 修复：把暂停做成**用户级**的状态，不跟着证书行走。做法任选其一：
  1. 新表 `user_data_licence_holds(user_id, paused_at, reason, actor)`，resume 时删除；
  2. PUT 时查 `ops.data_licence_events` 中该用户最近一次 pause/resume 事件。

  set_licence 的判断改成“该用户处于暂停中”。补测试：pause → DELETE → PUT，期望状态仍为 `paused_by_admin`，且没有投递验证。

**M2　重新 PUT 同一证书会清掉 quota_exceeded / ip_limited，绕过降级表（efcd244）**
- 位置：`service.py:200`（不是暂停就一律写 `PENDING_VERIFICATION`，并清掉 `paused_until`）。
- 原因：plan 第 356-365 行的降级表规定：101 暂停到次日 00:01，103 暂停 120 秒，1 小时内第 3 次暂停 1 小时。用户只要把同一证书再 PUT 一次（10 次/小时之内），就能立刻重置状态并触发外呼，这会放大对上游的 101/103，严重时可能导致上游封 IP，殃及所有用户。
- 修复：PUT 时如果 `licence_hmac` 与旧行相同，而且旧状态属于 `quota_exceeded` 或 `ip_limited` 且 `paused_until` 还没到，就沿用旧状态和 `paused_until`，不投递验证（响应 202，返回当前状态）。只有换了新证书才进入 `pending_verification`。补对应测试。

**M3　没有 DB 角色和列权限，验收第 766 行“api 角色 SELECT ciphertext 被拒”不满足（efcd244）**
- 位置：`migrations/versions/0007_t_b45_data_licences.py:19`（docstring 把授权推给运维）；`service.py` 的 `live_row(lock=True)` 直接读基表。
- 原因：视图 `app.user_data_licence_status` 不含密文，这只是约定，api 进程用的角色仍然能读 `ciphertext`。契约把“DB 角色拒绝”列为验收项，属于纵深防御的一层，不能只靠代码自律。
- 修复：在迁移里（或运维的 init SQL 里，二者择一，但要有可执行的脚本和测试）创建或配置 `app_api` 角色：
  - `REVOKE SELECT ON app.user_data_licences FROM app_api`；
  - `GRANT SELECT (id, user_id, status, …非敏感列) ON app.user_data_licences TO app_api`；
  - 授予 INSERT/UPDATE 的列级权限（写密文需要 INSERT 和 UPDATE `ciphertext`，但不给 SELECT）。

  `live_row(lock=True)` 的 `SELECT … FOR UPDATE` 只能选授权过的列；如果 `FOR UPDATE` 需要表级 UPDATE 权限，就改成 `FOR NO KEY UPDATE` 并逐列核对。补一个以 api 角色连接、`SELECT ciphertext` 期望 `permission denied` 的测试。ingest 用单独的角色。

**M4　ingest 的每证书调度、公平性、来源标记还没实现，验收 768-772 不满足（efcd244 / T-B04a，按 T-B04a-x 跟踪）**
- 位置：`app/workers/ingest.py`（只有心跳占位，外加遇到 `MAIRUI_LICENCE` 以 78 退出）；`config_files.py:258-285` 只在配置模型层锁死了 `mode: per_licence` 和 `allow_cross_licence_fallback: false`。
- 现状：
  - 没有 verify 消费者，所以 PUT 后状态永远停在 `pending_verification`；
  - 没有每证书令牌桶、DRR 公平调度、熔断和状态机（101/102/103）；
  - 行情行没有 `source_licence_id`；
  - 没有 SSE `data_licence` 推送；
  - 没有 `manual_refresh` 的 409。

  回放测试 `test_backend_has_per_licence_scheduler_and_state_machine` 和 `test_unusable_licence_reads_degrade_and_refresh_409[*]` 都失败（404，或找不到模块）。
- 配置层把“不回退到其他证书”锁死成了字面量，这一点做得好。但验收项里的“不回退”还要求运行时断言，配置锁死不能代替。
- 处理：T-B04a 不算完成，自报里应写明“接口层完成，调度层待 T-B04a-x”。T-B04a-x 完成前，生产环境不能开放证书设置入口；否则用户看到的永远是“验证中”。

**M5　改密接口的旧密码限速在校验之后，被盗会话可以无限猜旧密码（57b1c3b）**
- 位置：`app/api/v1/auth.py:327-332`。
- 原因：只有 `verify` 失败时才调用 `enforce`。超限以后，猜错返回 429，但**猜对仍然改密成功**。攻击者拿到会话后可以一直猜，直到命中后改密接管账号；429 和成功的差别还替攻击者确认了结果。
- 修复：校验前先 `peek` 当前窗口，已超限就直接返回 429，不跑 argon2；校验失败再记一次。也就是“先查、后验、失败记数”，与登录接口一致。补测试：超限后用正确的旧密码，期望 429，密码不变。

**M6　CI 门禁在 main 上是红的：契约检查脚本仍期望 23 个原因码，而且没有后端测试（跨任务：T-O02 / 测试，不算后端提交本身的问题）**
- 位置：`scripts/ci/check_contract.py:6`、`:30`（`EXPECTED_REASON_TOTAL = 23`，最后改动在 35f0139）；main 上没有 `tests/`，CI 的 backend job 收集为空。
- 原因：v0.2.5 删掉 `PROFILE_OR_CONSENT_MISSING` 后变成 22 个（见裁定 b），脚本没跟着改；测试分支也没合进来。
- 修复：脚本改为 22，最好从 `/meta/enums` 或契约表格动态计数，不要写死；合并测试分支，或在 CI 里检出固定版本的测试；同步更新测试分支里落后的 3 个断言（head 0007、Me 加 `data_licence_status`）。

### m（建议修）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `api/v1/data_licence.py:172-173` | `POST /me/data-licence/test` 在 `paused_by_admin` 时返回 `409 DATA_LICENCE_UNAVAILABLE`，但契约第 555 行只列了 NOT_SET、429、503；第 320 行说这个码是给“需要触发拉取的写操作”用的，勉强能套上，但契约没有写明 | 契约第 555 行补一句“暂停中 → 409 DATA_LICENCE_UNAVAILABLE `{status}`”（推荐），或者代码改成返回 202 但不投递。由 T-A 决定 |
| m2 | `reports/T-B04a.md` 与 `licences/hpke.py` 文件头 | 自报写的是“用 cryptography 公开 HPKE API”，代码实际是手写的 RFC 9180 Base 模式（因为公开 API 不支持 AAD）。我按 RFC 核对过密钥编排，没发现错误，但自报与事实不符 | 修正自报；加 RFC 9180 附录 A 的已知答案测试，以及 seal/open 往返测试（hpke.py 覆盖率 47%） |
| m3 | `auth/deps.py:101-106` | M1 的修复点没有测试 | 补测试：对端不可信时忽略 XFF；对端可信时取最右一跳；只有 X-Real-IP 时用它 |
| m4 | `deploy/nginx.conf`、`config.py:60` | nginx 目前绑在 <host>:8080，TLS 还没上。如果以后在前面加宿主机反代，nginx 的 `$remote_addr` 会变成那台反代的地址，所有用户共用一个 IP 限速桶 | 在部署文档里写明：外层反代必须配 `real_ip_header` 和 `set_real_ip_from` |
| m5 | `licences/service.py:249-257` | PATCH 改 `expires_on` 时不重新计算 `expired` 状态，也不记事件 | PATCH 后按新日期重算状态，并记一条 `updated` 事件 |
| m6 | `licences/seal.py` + `config.py` | 没有 `APP_MASTER_KEY` 时，去重 HMAC 密钥用每个进程临时生成的（只允许在 local/test）。多 worker 开发时，IN_USE 判断会因此失效 | 开发环境也要求固定的 master key，或者在 compose 的 `.env.example` 里给一个 |
| m7 | `auth/abuse.py` | 有 `purge_login_attempts`（清理 180 天前的记录），但没有任何调度去调用它 | 挂到运维的 cron 或 worker 上，补到 T-O 清单 |
| m8 | `api/v1/auth.py` 注册分支 | pending 上限是“先计数再插入”，并发时可能超过上限几个 | 用 advisory lock 或 `INSERT … WHERE (SELECT count) < N`；影响小 |
| m9 | `api/v1/data_licence.py` resume 分支 | 对没有暂停的证书调用 resume，也会写审计并返回 204 | 返回 204 不变（幂等），但不写审计，或在审计里标记 noop；契约第 684 行可以补一句“未暂停时 resume 为空操作” |
| m10 | `docs/plan.md:3033`（T-B33）、`:3051`（T-T17） | 仍写“23 个原因码”，与 plan 第 1136 行和契约第 280 行的 22 个矛盾 | 改成 22（见裁定 b） |
| m11 | 测试 `test_data_licence_t_t22.py` | `test_db_stores_ciphertext_only…` 的正则 `last` 把契约允许的 `last_verified_at`、`last_error_*` 也当成泄露；`test_admin_pause_not_set_409` 期望非管理员访问 `/admin` 得 403，但契约 §1.3（第 213 行）和 §9（第 743 行）要求 404。后端在这两处都是对的 | 交给测试修正：正则改为 `cipher\|hmac\|licence$\|mask`；非管理员访问 `/admin` 期望 404 |
| m12 | 迁移 0005 | 删 consents 表是不可逆的，降级只重建一张空表。契约允许这样做，但需要提醒 | 在运维手册里写明：执行 0005 前先备份 consents，如果还需要留存 |

## 4. 证书设计（v0.2.6）逐项核对

| 要求（契约行） | 现状 | 判断 |
|---|---|---|
| 只有 ingest 能解密（766） | api 只加载公钥；`main.py:30` 发现私钥（环境变量或 secrets 文件）就拒绝启动；`load_private_keys` 只给 ingest 用 | ✅；DB 角色这一层缺，见 M3 |
| 加密绑定 | HPKE X25519/HKDF-SHA256/AES-256-GCM；AAD 是 `mairui-licence\|v1\|{user_id}\|{row_id}\|{key_version}`，每次 PUT 用新的 row_id，密文不能挪到别的行或别的用户 | ✅ |
| 不回显（453、552） | 响应、错误消息、校验详情（`errors.py:_issue` 只用固定文案，不带 `input`）里都没有证书值；10 组格式错误的测试全部通过 | ✅ |
| 一证一户（767） | HMAC（从 master 派生）+ 部分唯一索引 `uq_user_data_licences_hmac_live`，并发冲突时 `map_integrity` 返回 IN_USE；DELETE 后可以再设 | ✅ |
| 删除即抹除 | CHECK 约束：deleted 行的 `ciphertext` 和 `licence_hmac` 必须为 NULL | ✅ |
| 审计 | `ops.data_licence_events` 由触发器保证只追加 | ✅；PATCH 不记事件，见 m5 |
| 限速 PUT 10/h、test 5/h（552、555） | 按用户计数，测试通过 | ✅ |
| 每证书令牌桶、DRR、熔断、不回退（768-772） | 只有配置模型，没有运行时 | ❌ M4 |
| 暂停与恢复（684） | 接口和审计都有；DELETE 后 PUT 可以绕过 | ⚠️ M1 |
| 降级状态（plan 356-365） | 重新 PUT 可以重置 | ⚠️ M2 |

## 5. 证书测试失败逐条（配临时公钥、`--runxfail`）

| 测试 | 原因 | 归属 |
|---|---|---|
| `test_db_stores_ciphertext_only_and_api_reads_status_view` | 测试的正则过宽 | 测试（m11） |
| `test_admin_pause_not_set_409` | 测试期望 403，契约要求 404 | 测试（m11） |
| `test_unusable_licence_reads_degrade_and_refresh_409[×5]` | manual_refresh 和降级读还没实现 | 后端 T-B04a-x（M4） |
| `replay/test_backend_has_per_licence_scheduler_and_state_machine` | 调度模块不存在 | 后端 T-B04a-x（M4） |

---

## 6. 裁定建议

### (a) `/admin/*` 是否不进 openapi.json？

**建议：不进公开的 openapi.json（维持 efcd244 的 `include_in_schema=False`），但契约要写明这一点，管理接口另做契约测试。**

依据：
- 契约 §1.3（第 213 行）规定非管理员访问 `/admin` 返回 404；§9（第 743 行）要求 404 逐字节相同、不带 `Allow` 头，目的就是不暴露管理接口是否存在。
- `main.py:37` 在所有环境都公开提供 `openapi.json`，`docs_url` 只在 local/test 开启。如果把 `/admin` 放进 schema，等于直接公布了管理接口。
- 契约第 4 行和 plan 第 2111 行都规定以契约为准，openapi.json 不是权威，所以不进 schema 不违反契约。
- 代价：plan 第 2171、2911 行的 schemathesis 只针对 OpenAPI 跑，测不到 `/admin`（`schemathesis.toml` 的注释已经说明了这点）。

需要补的：
1. 契约 §1.3 加一句“`/admin/*` 不出现在公开 openapi.json”；
2. 管理接口用 pytest 直接覆盖，或者只在 test 环境生成一份 admin schema 给 schemathesis 用。

目前后端只有证书的 3 个 `/admin` 路由，都已设 `include_in_schema=False`；以后新增的 `/admin` 路由也照此处理，建议挂一个统一的 admin router 来保证。

### (b) 原因码是 22 个还是 23 个？

**22 个。**

依据：
- 契约第 280 行写的是 22（“v0.2.5 删 PROFILE_OR_CONSENT_MISSING”）；
- 表 A 第 42 行记录了“23 → 22 个”；
- 验收第 777 行按 22 核对；
- 代码里 `ReasonCode` 和 `REASON_CODE_TABLE` 都是 22 个，迁移 0005 的 CHECK 也是 22 个（bd33f83、4162abb）；v0.2.4 没有改原因码；
- plan 第 1136 行已经是 22。

要改的：
- `scripts/ci/check_contract.py:30` 改成 22（M6）；
- plan 第 3033、3051 行改成 22（m10）；
- 测试分支里写死 23 的断言一并改掉。

### (c) 蜜罐字段

- **出处**：只出现在 plan 里。plan 第 1798 行写“蜜罐隐藏字段；注册请求最短填写时间（< 3 秒视为机器）”，第 2821 行也提到，第 2934 行把它派给 T-B03a。**契约没有写**，第 545 行的注册请求体里没有这些字段。
- **现状**：
  - 后端没有实现，`api/v1/auth.py:5` 写明“未实现”；
  - 前端完全没有，主工作树里也没有；
  - 而且 `RegisterIn` 设了 `extra="forbid"`（auth.py:47-48），前端今天如果发蜜罐字段，会得到 `400 VALIDATION_ERROR unknown field`，等于直接暴露了这个机制。
- **建议**：
  - **写进契约**：前后端都要按它实现，而且 `extra="forbid"` 下不写进契约就没法发。
  - 字段：在注册请求体里加两个可选字段：
    - `website: string`：隐藏输入框，必须为空，名字要像一个真字段，方便诱捕机器人；
    - `form_started_at: int`：表单渲染时的毫秒时间戳。
  - 命中规则：`website` 非空，或者 `now - form_started_at < 3000`。
  - 命中后的处理：
    - 返回与正常注册**完全相同**的响应（V1 是 open 模式时返回 201 pending 的形状），不创建用户，避免机器人据此调整；
    - 写一条 `login_attempts` 或审计记录（`kind=honeypot`）；
    - 照常计入 IP 限速；
    - closed 或 invite 模式下仍按原规则返回 503。
  - `form_started_at` 缺失时不算命中，兼容老客户端；只按 `website` 判断。
  - 前端：用 CSS 移出视口来隐藏（不要用 `display:none`，有的机器人会跳过），设 `autocomplete="off"` 和 `tabindex="-1"`，加 `aria-hidden`。
  - 契约改好之前，前后端都不要单方面上线。

### (d) 暂停中能否 PUT 新证书？

**建议：允许 PUT（可以保存或更换证书），但暂停不解除，状态仍为 `paused_by_admin`，不投递验证；返回 `202 DataLicenceStatus`，其中 `status: "paused_by_admin"`。只有管理员 resume 才能解除暂停，解除后进入 `pending_verification` 并重新验证（契约第 684 行）。**

依据与现状：
- 契约第 552 行只写了 PUT 返回 202 和 `pending_verification`，没有覆盖暂停的情况；第 684 行规定 resume 后才是 `pending_verification`，可以推出暂停只能由管理员解除。
- 现有代码 `service.py:191-200` 正好实现了这个行为：沿用暂停状态，`verification_id` 为 None。

需要补的：
1. 契约第 552 行加一句“暂停中 → 202，`status: "paused_by_admin"`，不验证”；
2. 修掉 M1：暂停要做到用户级，否则 DELETE 后再 PUT 就能绕过；
3. 同理（M2），重新 PUT 同一证书时，`quota_exceeded` 和 `ip_limited` 要保留到 `paused_until` 为止；
4. 暂停中 `POST /test` 的行为写进契约（m1）。
