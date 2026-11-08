# 评审 6670b10（T-B49）

- 评审人：项目架构师；时间：2026-11-01 19:45（America/Denver，UTC-7）
- 方式：只读，在 /tmp 的干净导出（git archive 82b612b，后端 `uv sync --frozen`）里做；自起临时容器 arv-b49-pg（timescale 2.31.0-pg16）、arv-b49-redis（7.4.12-alpine），只绑 <host>，用完已删除；角色口令是一次性随机 hex，不是任何环境的真实值。未推送，未调用麦蕊。
- 对照基线：46538a6（本提交的父提交）。

## 结论：可以推送（有条件）

没有阻塞项。推送后 tester CI 会多出 7 个失败，全是测试需要跟进的已知变化（见 §3），与 T-B49.md 的预告一致。两个 T-T25 主要项（冷却用 DB 时间、删除 CLI 触发器白名单）没完成，列为后端下一步的必做项。

## 1. 实测

| 项 | 结果 |
|---|---|
| selfchecks/tb49.py（真实 PG+Redis，已应用 grants.sql） | **79 passed / 0 failed** |
| 0017 升级前预检查：放一条 purpose=plan、user_id 为空的行 | 升级被拒，报 `RuntimeError: 0017 预检查失败…（plan=1）`，版本停在 0016，数据没动 ✓ |
| 0017 干净升级 | 新增 horizon 进 `ck_data_snapshots_purpose`，新增 `ck_data_snapshots_user_scoped` ✓；horizon 且 user_id 为空 → 23514 拒绝 ✓；alert 且 user_id 为空 → 允许 ✓ |
| 0017 → 0016 降级（无 horizon 行） | 成功，user_scoped 约束删除 ✓；再升回 0017 成功 ✓ |
| 降级时库里有 horizon 行 | 降级失败，报的是 PG 通用错误 `check constraint "ck_data_snapshots_purpose" … is violated by some row`；事务回滚，两条约束都还在 ✓（但没有显式预检查和中文提示，见 m3） |
| tester 全套（wt-tests-T-T01 的 fb35b0f，导出到 /tmp） | 本提交：1056 passed / 16 failed / 12 xpassed；基线：1062 passed / 7 failed / 1 xpassed。**新增失败正好 7 个**，新增 XPASS 11 个（R6 ×5、D 项 ×4、T-O11 D ×2） |
| 契约检查（只看文档） | 通过 |
| check_code_namespaces（--meta-json） | 通过 |
| check_contract --meta-json | **失败**：`/meta/enums 缺少契约 §3 的枚举 plan_condition_type、plan_status`。基线 46538a6 也一样失败，meta 输出前后完全相同，所以不是本提交引入的（来源：契约 #30，66f0c79）→ 见 M3 |

两次全套都有 3 个失败，跟本提交无关：test_repo_yaml_loads_in_settings（tester 分支的 config 缺 securities）、test_api_role_cannot_select_ciphertext、test_d_grants_who_may_insert（角色 tt25d_maint 不存在）。另外 test_contract_live 会打本机默认 BASE_URL 上别人起的服务，那边还是没声明 414 的旧版本，结果不算在本提交上。

## 2. 逐条核对本提交的说法

| 说法 | 核对 |
|---|---|
| /portfolio 按 #31：日线收盘价优先，cash/total_assets/cost_price/weight_pct 不为 null，只有 sector 缺口时不降级 | ✓（tester R6 五条转 XPASS）。T-T25 #6：security_type 为 null 的行不读快照参考价（price=None + 缺口）✓。缺口原因：positions.* 一律用 no_source ✓；cash 缺口仍是 user_input_missing，按 T-B46 ③ 是对的 |
| master key 按服务区分 | ✓。SERVICE_NAMES 白名单；只有 api、worker 需要；ingest 在所有环境都禁止（ingest.main 退出 78）；非 local/test 环境缺 key 抛 MasterKeyMissingError；所有派生路径都走 `master_key_bytes()`；compose 给每个服务都设了 SERVICE_NAME |
| 0017 有违规行预检查，升级/降级都验证过 | 升级预检查 ✓（实测）。降级：见 m3 |
| ETF 在 data_source 不为空时才不按 T+1 | 部分对，见 m2 |
| RC4 行业缺口 | ✓ rc4 启用时补 `{fit_assessment.sector, no_source}` |
| 删除 CLI 只接受 _FILE，dry-run 核查角色 | ✓：设了明文环境变量就 SystemExit；dry-run 拒绝服务角色、超级用户、库或 app/ops/market 对象的属主、对这些 schema 有任何写权限的角色 |
| 冷却清理走 beat/worker，半开区间，用 DB 的 UTC 时间 | beat/worker 链路 ✓，半开边界 ✓；**DB 时间 ✗**，见 M1 |
| OpenAPI 声明 414 | ✓：41 个操作全部声明了 UriTooLongResponse（code 固定为 URI_TOO_LONG，不进 ErrorCode）。契约和 plan 里还没有 414，见 m4 |
| delisting 文案 | ✓ “该证券处于退市整理期（简称带“退”）” |

## 3. 问题

**B：无。**

**M（主要）**
- **M1 冷却过期判定用的是应用时钟，不是 DB 的 UTC 时间（T-T25 #5）。** jobs.py 的 purge 和 `_take_cooldown` 用的都是 `now_utc()`（`datetime.now(UTC)`），写 `deleted_at` 也用这个。应改为 SQL 里的 `now()`/`clock_timestamp()` 做比较和写入（比如 `WHERE paused_until <= now()`），自检要补一条应用时钟偏移的用例。→ 后端
- **M2 删除 CLI 的触发器白名单没做（T-T25 #4）。** 代码里没有 pg_trigger/tgisinternal 自检；tester 的 `test_purge_trigger_allowlist_execute_refuses` 在基线上是 xfail。要求：dry-run 输出白名单差异，`--execute` 遇到白名单外的触发器就拒绝，并且不提供跳过开关。→ 后端
- **M3（不是本提交引入）/meta/enums 缺 plan_status、plan_condition_type，CI 的契约任务是红的。** → 后端 T-B50
- **M4 T-T25 剩下的后端项都还没提交**：on_demand 触发 CHECK 的迁移（工作区里有别的代理没跟踪的 0018 草稿，我没动）；R11 #9/#10 收紧 schema（trades 的 qty/price、imports 的 encoding_override）；计划草稿超过单笔上限要截断（plan-drafts 接口还没有）。→ 后端

**m（次要）**
- m1 /portfolio 的 fresh/stale：现在只要有价就是 STALE，没价才是 FRESH，所以当天的收盘价也会显示 stale。这和 T-B49.md §1.3（“日线不是最近交易日的为 STALE”）以及契约（“按现价时点取 fresh/stale”）不一致。应按交易日历判断。→ 后端
- m2 ETF 门槛 `if t0.data_source is None`：空串 "" 不会被当成缺失。plan 写的是“null 或空串时所有 ETF 返回 T+1”。应在 config 加载时把空白规范成 None，或者判断时用 `not (data_source or "").strip()`。→ 后端
- m3 0017 降级没有显式预检查：有 horizon 行时只报 PG 通用错误。安全性没问题（事务回滚），但和 T-T25“有则拒绝降级，给出原因”的写法不一致。建议先计数，再抛出中文 RuntimeError。另外 data_snapshots 只能追加，库里已有违规行时没有经过认可的清理路径，T-B49.md 应写明怎么处理（例如走 purge_permits 或删除 CLI）。→ 后端
- m4 契约和 plan 里没有 414/URI_TOO_LONG（grep 为空），但 nginx 和 OpenAPI 已经在用。→ 架构师：在契约里补“网关自产错误码”，不升版本号，并说明不进 /meta/enums
- m5 运维：compose 里还留着 cooldown-purge 服务，要删掉；worker 用的是属主 DSN，原来的 purge 用的是 aia_api，需要定下来用哪个。→ 运维/架构师

## 4. 谁做什么
- 后端：M1、M2、M4、m1、m2、m3；M3 归 T-B50（还有 T-B49.md 提出的“JSON 格式错误先于 401 返回 400”，也归 T-B50）。
- tester：把这 7 个用例改到新行为：test_alembic_head_is_known 加 0017；test_a11_09、t_t24 ×3、t_t25c ×2 改用 `AIA_MAINT_DATABASE_URL_FILE` 和非超级用户的 aia_maint DSN。把转成 XPASS 的 11 个 xfail 标记摘掉（test_t16_writer_asserts_user_id 等）。
- 运维：上共享库之前先跑 0017 的预检查 SQL，有行就停下来上报；删掉 cooldown-purge 服务；worker 的 DSN 按架构师的决定配。
- 架构师：m4；worker DSN 的决定。
