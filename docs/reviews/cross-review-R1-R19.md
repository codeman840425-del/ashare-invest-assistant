# 异源复核交接包：R1–R19、B1–B4（T-A95）

> 状态：已入库（架构师 T-A95，2026-11-09 America/Denver），基线 main=0e2e66c（第 4 批：含 be/T-B116f=bda9694、契约 docs/T-A92=8c7780f、test/T-T58=81a4f83、T-B116g=9cccbd7）。T-A99（2026-11-09 America/Denver）按 **main=b6ba5f9**（第 5 批，含 72d1f3a）重核行号，并在 R19 登记 T-A98 三项。
> 本文行号以 **b6ba5f9** 为准，已逐项复核。相对 0e2e66c，`docs/plan.md` 因 T-A96 在 :114 附近插入 4 行，其后行号均 +4（已改正文引用）；其余已引源码与契约文件未变。标「按 3369d3b」「按 8e847d5」的行号沿用原评审。
> 读者：新团队的复核 Bot。本队口径是「架构师评审 + 测试先红后绿」为合入门槛，下列各项另需不同模型或团队独立复核。
> 引用规则：只引用仓库内路径。团队内部、尚未入库的评审记录写作「团队评审记录 T-Axx（未入库）」，复核方无法直接查看，只当作背景。

## 0. 收敛口径（编排者定，复核方请按此口径判定阻塞）

- 只有两类算**阻塞**：
  - **(a)** 正常业务代码会误走的路径，包括误拦合法业务调用，以及正常写法漏拦；
  - **(b)** 契约（`docs/api-contract.md` §7.11.5）已明确承诺拦截的写法却没拦住。
- 其余**刻意对抗**的绕过一律**不阻塞**，登记到 R19 作为残余风险，由运维 T-O68 的容器网络层和异源复核兜底。例如 `ctypes.cast` 裸地址、钩子安装前已建好的 socket、C 扩展直接调 libc。
- 请复核方对每条发现标明归 (a)、(b) 还是「对抗性残余」。若认为口径本身不妥（例如某类对抗写法其实是正常代码常见写法），请单独说明。

## 1. 总表

| 编号 | 类别 | 主题 | 状态 | 优先级 |
|---|---|---|---|---|
| R1 | 数据删除 | 0030 purge 删除范围（scope 并集、共享即整笔回滚） | 已合入，待异源复核 | 中 |
| R2 | 数据库安全 | purge 函数 SECURITY DEFINER 越过 RLS、search_path | 已合入，待异源复核 | 高 |
| R3 | 授权 | EXECUTE 只授 aia_maint、PUBLIC 撤销、db-roles 重跑不反转 | 已合入，待异源复核 | 中 |
| R4 | 数据删除 | 漂移守卫是否够；不走外键的隐式用户关联列（已逐表核对，均已处理） | 已合入，待异源复核 | 中 |
| R5 | 限流 | IP 限流按 user_id 计数、换证继承计数是否过严 | 已合入，待异源复核 | 中 |
| R6 | 限流 | 回填 SQL「标记后、窗口内」计数与 last_mark+pause_s 截止（边界缺口 G1–G5） | 已合入，待异源复核 | 中 |
| R7 | 风控 fail-closed | 限流升级 fail-closed 全口径（写失败、补写、库挂停 1h） | 已合入，待异源复核 | 高 |
| R8 | 并发 | 咨询锁 hashtext 碰撞；多副本时内存过期 | 已合入，待异源复核 | 低（现为单副本） |
| R9 | 接线 | state.py IP_LIMITED 改为抛错，须统一走 IngestCore.complete | 已由 M-1 接线落实，待异源复核 | 低 |
| R10 | 限流 | 补写用调用方原始 at 回填、重置计数基线；多 pending 只留最后一个 | 已合入，待异源复核 | 低 |
| R11 | 时钟 | 时钟来源（L-3 未采纳，单副本同主机时钟） | 暂缓，待异源复核 | 低 |
| R12 | 风控（M-1） | ingest 麦蕊单一出口整体方案 | 已合入（0e2e66c），待异源复核 | **最高** |
| R13 | 文件安全 | TEMP 创建/清理依赖 single-egress 锁的前提 | 已合入，待异源复核 | 中 |
| R14 | 风控 | 检查与锁顺序、停机优先级 | 已合入，待异源复核 | 高 |
| R15 | 风控 | 超时上界（准入 ≤3s、pg_locks 时限、⑦再核 0.5s）与残余挂起 | 已合入，待异源复核 | 高 |
| R16 | 风控 | 静态守卫 S1–S6、S2b 有限清单与不覆盖项 | 已合入，待异源复核 | 高 |
| R17 | 风控（M-2） | 证书状态以库为准、102 后必拒、lease 不可伪造 | 已合入，待异源复核 | 高 |
| R18 | 风控（M-a/M-c） | lease HMAC/线程/pg_locks；写库失败同写 HALT、退出码 74/78 | 已合入，待异源复核 | 高 |
| R19 | 风控（运行时） | netguard 审计钩子、公网默认拒绝、对抗性残余 | 已合入，待异源复核 | 高 |
| B1 | 策略发布门槛 | 「统一 20 日」只指发布资格窗，n 取映射跟踪期 complete 数 | 已裁定；代码未定位 | 中 |
| B2 | 策略计数 | 缺 horizon 的观测不进 n | 已裁定；RC5 侧已有（8219665） | 中 |
| B3 | 门禁语义 | G6 warn 经 ack 只留审计，不挡信号、不降权 | 已裁定；现状即口径（c6ce767） | 中 |
| B4 | 策略发布门槛 | S-01 以 T+5 为主口径，资格计数取 T+5 complete | 已裁定；代码未定位 | 中 |

**编号冲突（请复核方知悉）**：`docs/reviews/T-A76-tb110-review.md` §4 的表把 T-A74 的 B1–B4 记作 R5–R8。之后团队评审记录 T-A79（未入库）起，R5–R8 改用于 IP 限流的四项，B1–B4 单列。本包以后者为准：R5–R11 指限流和时钟项，B1–B4 指 T-A74 裁定。已在 `docs/reviews/T-A76-tb110-review.md` §4 表下加一行勘误（编排者同意），文字如下：

> 勘误（T-A95）：本节表中「R5–R8」即 T-A74 裁定的 B1–B4（`docs/reviews/T-A74-rulings.md:43-46`），与团队后续编号冲突；自 T-A79 起 R5–R11 指 IP 限流与时钟项，B1–B4 单列。以 `docs/reviews/cross-review-R1-R19.md` 为准。

---

## 2. R1–R4（T-B110 门控事实清除 0030 / T-O60 授权）

共同来源：`docs/reviews/T-A76-tb110-review.md` §4（行号按 3369d3b）。涉及提交 be/T-B110=3369d3b、ops/T-O60=80ed9f1，两者都已在 main。

### R1 purge 删除范围
- ① 问题：0030 的 purge 按 scope 并集删除，包括「目标用户的绑定指向、但 origin 是别人证书」的 scope（评审问题 9）。只要有他人绑定仍引用，整笔回滚（`gate_scope_shared`）。
- ② 位置：`src/backend/migrations/versions/0030_ta73_purge_gate_facts.py:47-92`；`src/backend/app/cli/delete_user_data.py:973-986`（--execute 先 purge，再删证书行）。
- ③ 请回答：
  - 并集口径会不会多删他人可用的门控事实？
  - 「共享即整笔回滚」是否会让用户删除请求长期无法完成？
  - 按「门控事实归属绑定」理解是否合理？
- ④ 我方结论：按归属绑定口径可以接受；负例（非 purging 用户调用返回 `gate_purge_requires_purging_user`）与旁观者保留已实测，见 `docs/reviews/T-A76-tb110-review.md` §3。用例：`tests/backend/api_app/test_delete_user_data_cli_t_t24.py`、`src/backend/selfchecks/test_tb110_gate_purge.py`（后者为源码字符串断言，评审问题 2 指出缺 PG 行为用例）。
- ⑤ 残余：评审问题 2 的 PG 行为用例未补齐；问题 4 dry-run 不检查共享 scope（`--execute` 才报 `gate_scope_shared`）。均不挡合入。

### R2 SECURITY DEFINER 与 RLS
- ① 问题：purge 函数属主是库属主（compose 下为超级用户），以 SECURITY DEFINER 运行并越过 RLS（两表 `relforcerowsecurity=false`）。
- ② 位置：`0030_ta73_purge_gate_facts.py:14-19、47-51`（0e2e66c 中 `SECURITY DEFINER` / `SET search_path = pg_catalog` 在 :18-19、:50-51）。
- ③ 请回答：
  - search_path 固定为 pg_catalog 是否足够防注入或劫持？
  - 函数体是静态 SQL、参数只有 uuid，是否还有提权面？
  - 属主是否应改为非超级用户专用角色？
- ④ 我方结论：静态 SQL、uuid 参数，未发现注入面（T-A76 评审问题 8，信息级）。
- ⑤ 残余：属主即超级用户这一点未改。

### R3 EXECUTE 授权
- ① 问题：EXECUTE 只授 aia_maint、撤销 PUBLIC；db-roles 重跑后不能反转；T-O57 授权不被破坏。
- ② 位置：`deploy/db/roles/grants.sql:109、461-465、483`（按 3369d3b/80ed9f1）；`deploy/db/roles/verify-roles.sh:491-494`。
- ③ 请回答：
  - 授权是否最小？
  - apply-roles 非单事务（评审 O-1，先授后撤，中途失败会残留）是否可接受？
  - verify-roles 把函数缺失判 OK（O-2）是否需要改？
- ④ 我方结论：T-O60 通过，两次 db-roles 后 api/ingest/PUBLIC=f、maint=t，verify-roles 234/0，四种破坏均 rc=1（T-A76 补评）。
- ⑤ 残余：O-1、O-2 未修。`$vendor_grant$` 与 `$o33$` 口径矛盾（grants:724/731 对 1132）未统一。

### R4 漂移守卫与不走外键的隐式用户关联
- ① 问题：ingest_private 被排除出外键扫描后，靠漂移守卫 `_ingest_private_user_fk_drift` 兜底。守卫只看「指向 app.users 的外键」，不走外键的隐式关联列是否都被 CLI 显式处理？
- ② 位置（0e2e66c）：
  - `src/backend/app/cli/delete_user_data.py`：
    - `_market_licence_tables` :600
    - `_ingest_private_user_fk_drift` :619-640
    - `_unhandled_fk_refs` :642
    - `_INGEST_PRIVATE_USER_FK_ALLOWED` :403
    - 匿名化步骤 :121-165
    - 删除与解除引用步骤 :268-325
    - gate purge 调用 :975
  - 迁移 `src/backend/migrations/versions/0001`–`0030`，表定义 `src/backend/app/db/tables/*.py`。
- ③ 请回答：
  - 下表「CLI 处理」是否完整？
  - 新增不走外键的用户关联列时，现有守卫（只认外键）发现不了。是否需要按列名或注释约定再加一道守卫？
- ④ 我方结论：逐表核对了迁移 0001–0030 与 `app/db/tables`，按列名匹配 user/actor/owner/*_by/admin/reviewer/requester/licence_id/target_id/username，再逐列判断语义。结果如下：
  - 带外键的列：不论指向 app.users、app.accounts 还是 app.user_data_licences，都由外键扫描或按账户、证书的级联步骤覆盖，未逐列列出。
  - 不走外键、但关联到用户的列见下表，都已被 CLI 显式处理。没有发现「关联到用户、却未处理」的列。

| 表.列 | 是否有外键 | 关联方式 | CLI / 迁移处理 | 影响 |
|---|---|---|---|---|
| ingest_private.mairui_gate_scopes.origin_licence_id（0029:16） | 无 | 指向用户证书 id | 0030 purge 以 origin 证书并集选取 scope（0030:64-75），在删证书行之前调用（CLI:975） | 不先 purge 就删证书会留下孤儿 scope；守卫不覆盖此类列 |
| ingest_private.mairui_gate_bindings.tag（0029:23） | 无（bytea） | 随 binding 行 | 随 `user_id` 整行删除（0030:85） | 无独立风险 |
| app.audit_logs.actor_id（uuid）、target_id（text） | 无 | 用户 id / 对象 id 文本 | 匿名化（CLI:123-133，`purge_target_ref`、`purge_scrub_json`） | 保留审计行、去标识 |
| app.risk_control_settings_history.user_id（0001:1284） | 无 | 用户 id | 显式删除（CLI:272，`user_id` 或 setting_id 子查询） | 已处理 |
| app.non_executable_reasons.released_by（text，'system' 或 user_id） | 无 | 用户 id 文本 | 解除引用（CLI:312） | 已处理 |
| app.login_attempts.username_tried | 无 | 用户名 | 按用户名删除（CLI:289） | 已处理 |
| app.invite_codes.bound_username | 无 | 用户名 | 解除引用（CLI:300） | 已处理 |
| ops.ingest_request_log.licence_id（0007:245，hypertable 无外键）、requester、dedup_key | 无 | 证书 id / 文本 | 匿名化（CLI:156，`licence_id = ANY(:lids)`，requester/dedup_key 按 id 模糊匹配） | 已处理 |
| app.notifications.target_id、app.llm_calls.target_id（text） | 无 | 对象 id 文本 | 按用户对象 id 集合解除或删除（CLI:145-153、317-319） | 已处理 |
| market.security_reconciliation_diffs.source_licence_id（0019:308）、market.master_vendor_batches.source_licence_id（0020:45） | 无 | 证书 id | 运行时动态发现 market 下带该列的表，按证书删除（CLI:600-614） | 已处理；CLI 模块文档 :27 仍写「当前库内尚无此列」，属过时注释（信息级） |

  - 按列义判定**不是用户标识**的列（未逐行验证数据）：
    - `app.feature_catalog.owner`、`app.suggestions.generated_by`：生成方或团队；
    - `app.risk_events.subject`：风控对象，行本身按 user_id 外键删除；
    - `ops.ingest_leases.holder_host`：主机名；
    - `ops.data_licence_events.actor`：枚举 user/admin/ingest；
    - `app.audit_logs.actor_role`；
    - `app.strategy_instances.paused_by`：枚举 user/system。
  - 实测证据：在 ingest_private 中多加一列指向 users 的外键，会被列为阻断（`docs/reviews/T-A76-tb110-review.md` 漂移守卫反例段）。
- ⑤ 残余：
  - 漂移守卫与 `_unhandled_fk_refs` 只认外键。今后在任何 schema 新增「不走外键的用户关联列」（uuid/text/bytea），两道守卫都发现不了，只能靠评审。
  - 动态发现只覆盖 market 下名为 `source_licence_id` 的列。
  - 本次核对靠列名匹配加人工判读，没有起库查 pg_catalog 全量列。

---

## 3. R5–R11（IP 限流升级与补写，T-A75 方案及其后续）

共同来源：`docs/reviews/T-A75-ratelimit-escalation-fix.md`（方案 A：按 user_id 计数，复用 `ops.data_licence_events`，启动、新 id、user_reset 时回填，写库失败按已升级处理）。后续修订见团队评审记录 T-A79、T-A81、T-A84、T-A86（未入库）。
代码：`src/backend/app/ingest/ip_limit.py`（`_write_event` :61、`rehydrate` :86、`acquire_ip_limit_lock` :157、`flush_pending_escalation` :164、`record_hit` :197）、`src/backend/app/ingest/core.py`（`_try_flush_pending` :103、`rehydrate_locked` :127、`rehydrate` :153）。
用例：`tests/backend/unit/test_ta75_ip_limit_escalation_t_t41.py`、`tests/backend/unit/test_ta81_l6781_t_t45.py`；`src/backend/selfchecks/test_tb111_*`、`test_tb112_*`、`test_tb113_*`。

### R5 按 user_id 计数
- ① 问题：计数键为 user_id，换证也继承计数，比契约 #13 严。
- ② 位置：`ip_limit.py:197`（record_hit）；方案文 `docs/reviews/T-A75-ratelimit-escalation-fix.md`。
- ③ 请回答：按用户而非按证书计数是否过严？会不会误伤同一用户的合法换证？
- ④ 我方结论：这样能同时堵住删掉后重加、重启、点测试三条绕过路径。证书指纹不可用，因为 ingest 不得持主密钥。
- ⑤ 残余：换证后仍沿用旧计数，属有意为之。

### R6 回填 SQL 截止与边界用例
- ① 问题：回填 SQL 计数「标记后、窗口内」，截止为 last_mark+pause_s。
- ② 位置：`src/backend/app/ingest/ip_limit.py`：
  - `rehydrate` :86-122：
    - last_mark 取最新一条 `paused→ip_limited`（`ORDER BY at DESC LIMIT 1`）；
    - 命中条件 `at >= :ws`，有标记时再加 `at > :mark`；
    - `escalated_until = last_mark + pause_s`。
  - `trim_hits` :55（内存用 `< start` 丢弃，与 SQL 的 `>=` 一致）、`merge_rehydrated` :125（不缩短内存截止）。
  - `record_hit` :197：命中与升级标记写同一个 `at=now`。
  - 截止判断见 `src/backend/app/ingest/state.py:98-101、129-133`：`now < effective` 时拒绝，`now >= effective` 时恢复。
- ③ 请回答：
  - 下列边界语义是否正确？
  - 缺口是否需要在合入前补用例？
- ④ 我方结论：边界语义自洽。升级那一击与标记 `at` 相同，`at > :mark` 的严格不等号正好把它排除，从下一击起重新计数。已有用例：

| # | 边界 | 用例（0e2e66c） | 走 PG SQL 路径？ |
|---|---|---|---|
| E1 | 无标记时窗口内命中回填，重启后第三击升级；标记 1 条，`escalated_until = t3 + pause_s` | `tests/backend/unit/test_ta75_ip_limit_escalation_t_t41.py::test_ta75_t2_restart_rehydrates_and_escalates` | 是（需 TT41_DATABASE_URL） |
| E2 | 两次 bootstrap 后计数仍在 | `tests/backend/unit/test_tb114_bootstrap_restart_t_t47.py::test_tb114_two_starts_escalation_count_persists`；自检 `src/backend/selfchecks/test_tb114_restart_persist.py` | 是 |
| E3 | 有标记时由 last_mark 得截止；新进程截止前拒绝，`pause_s + 1` 后放行（补写用原始 at） | `test_ta75_ip_limit_escalation_t_t41.py::test_ta81_l9_flush_then_restart_still_refuses` | 是 |
| E4 | `at == now − window_s` 的命中仍计入 | `test_ta75_ip_limit_escalation_t_t41.py::test_ta75_t4_window_boundary_at_equals_now_minus_window_counts` | 否（仅内存） |
| E5 | 标记后从 1 重新计；用户间隔离 | `test_ta75_ip_limit_escalation_t_t41.py::test_ta75_t4_isolation_and_post_mark_recount` | 否（仅内存） |
| E6 | 删除重加、user_reset、重启三条绕过 | `src/backend/selfchecks/test_tb111_bypasses.py`；t_t41 的 T1、T3 | 部分 |

  缺口（尚无用例）：
  - G1：SQL 的 `at >= :ws` 等号边界没在 PG 上测（E4 只测内存）。
  - G2：SQL 的 `at > :mark` 严格不等号没在 PG 上测，即升级那一击（与标记同 `at`）重启后不应计入，标记前、窗口内的命中也不应计入（E5 只测内存）。
  - G3：截止等号 `now == last_mark + pause_s` 应放行；现有用例都用 `+1s`。
  - G4：多条标记取最新；补写的原始 at 早于已有标记时（与 R10 叠加）计数基线不回退。
  - G5：时区：PG timestamptz 回读与非 UTC 的调用方 now 比较；现有用例都用 UTC 的 NOW0。
- ⑤ 残余：G1–G5 未覆盖。代码读下来语义正确，但没有 PG 定点用例锁定。建议由测试补 G1–G3（不挡合入）。

### R7 fail-closed 全口径
- ① 问题：写失败按已升级处理，单次命中也会落 1h 标记；补写失败的处理；启动时库挂了会把所有用户停 1h。
- ② 位置：`core.py:103-125`（`_try_flush_pending`：提交成功后才清 pending）、`core.py:127-190`；`ip_limit.py:164`。
- ③ 请回答：
  - 1h 暂停在库抖动场景下是否代价过大，是否应改为短暂停？对应 `docs/plan.md` §T-A87「未决」①（:3864）。
  - 补写语义是否完备？
- ④ 我方结论（最新）：L-6、L-8 已修，即提交成功后才清 pending、tick 补写、用原始 at、幂等。tick 等锁限 2s；库挂起由 L-1 的 ingest profile 超时兜底（`src/backend/app/db/engine.py:28-45`）。M-b 起准入路径的 flush 在 SAVEPOINT 内（A29、A31）。用例 `test_ta91_a28_a32_t_t55.py` 的 A31 两例，含「flush 成功但外层提交失败 → pending 保留」。
- ⑤ 残余：重启前未补写则丢失（仅在内存中）；启动时库挂了全员停 1h。

### R8 hashtext 碰撞与多副本
- ① 问题：咨询锁键用 `hashtext`，存在碰撞；多副本时，另一进程在下次回填前仍会放行（内存过期，已实测）。
- ② 位置：`ip_limit.py:152-161`；single-egress 锁 `src/backend/app/ingest/egress.py:200-222`。
- ③ 请回答：碰撞只导致串行化（误等待），还是可能误放行？
- ④ 我方结论：当前单副本，风险低（见团队评审记录 T-A79、T-A84，未入库）。
- ⑤ 残余：多副本部署前必须重审。

### R9 IP_LIMITED 统一走 IngestCore.complete
- ① 问题：`state.py` 中 IP_LIMITED 改为抛 RuntimeError，接线时必须统一走 `IngestCore.complete`。
- ② 位置：`src/backend/app/ingest/state.py:171`；`egress.py:448` 起 `mairui_get`，限流路径先写 HALT（:520），再 `core.complete`。
- ③ 请回答：是否还有绕过 `complete` 直接调 `LicenceState.on_result(IP_LIMITED)` 的路径？
- ④ 我方结论：M-1 接线后所有外呼经 `mairui_get`，完成后调 `core.complete`；A4 覆盖「假 103 → 写事件并 HALT」。
- ⑤ 残余：无已知。

### R10 补写时间语义
- ① 问题：补写标记用调用方时钟的原始 at 回填历史时间，同时重置计数基线（at>last_mark）；多个 pending 只保留最后一个。
- ② 位置：`ip_limit.py:164-196`、`:251`（queue_pending_escalation）。
- ③ 请回答：这种语义能否接受？只留最后一个 pending 会不会丢失更早的升级？
- ④ 我方结论：团队评审记录 T-A81（未入库）认为可接受，待异源确认。
- ⑤ 残余：如上。

### R11 时钟来源（L-3 未采纳）
- ① 问题：写库用调用方时钟而不是库时钟。
- ② 位置：`ip_limit.py:61`（`_write_event`）、`:106`（窗口）。
- ③ 请回答：单副本、PG 与 ingest 同主机同内核时钟时，只剩时钟跳变风险，这个判断是否成立？
- ④ 我方结论：暂缓。以后多副本或用远端 PG 时，改为 record_hit 在事务开头 `SELECT now()`，内存和写库统一用它，补写仍用原始 at（团队评审记录 T-A84，未入库）。
- ⑤ 残余：时钟跳变。

---

## 4. R12–R19（风控重点：ingest 麦蕊统一出口 M-1/M-2/M-a/M-b/M-c 与两层守卫）

共同契约：`docs/api-contract.md` §7.11.5（:1352-1412）。共同方案：`docs/plan.md` §T-A87（:3736-3865）。其中：
- fail-closed 矩阵 :3771
- 锁关系 :3793
- 验收 34 条 :3799、:3822（T-A91 表）、:3836（T-A92 口径裁定表）
- R 项 :3859-3862
- 未决 :3864

主要代码：`src/backend/app/ingest/egress.py`、`src/backend/app/ingest/netguard.py`、`src/backend/app/workers/ingest.py`、`src/backend/app/ingest/core.py`、`src/backend/app/ingest/daily_lists.py`。
提交链（均在 main=0e2e66c）：
- 契约：50c930d（T-A87）→ 9ca4c0f（T-A89）→ a5b94b3（T-A91）→ ecb4cbb（T-A92）→ 8c7780f（T-A93）
- 后端：be/T-B116 → T-B116b/c → T-B116d=ab7ec5b → T-B116e=9435ad0 → T-B116f=bda9694
- 测试：T-T50/52/55/56/57/58（81a4f83）

正式用例：
- `tests/backend/unit/test_ta87_m1_a1_a24_t_t50.py`（A2–A24）
- `test_ta87_m1_a1_a27_t_t52.py`（A25–A27）
- `test_ta91_a1s_static_t_t55.py`（A1s）
- `test_ta91_a1r_runtime_t_t55.py`（A1r）
- `test_ta91_a28_a32_t_t55.py`（A28–A32）
- `test_ta93_b4_admit_lease_audit_t_t58.py`（B-4）

后端自检：`src/backend/selfchecks/test_tb116*`。
我方最新结论：bda9694 可合。正式用例和自检在普通模式与 `python -O` 下全绿（团队评审记录 T-A94，未入库）。

### R12 M-1 单一出口整体方案
- ① 问题：原先 ingest 外呼不经限流核心（IngestCore 空壳接线）。方案是 `app/` 内只有 `egress.mairui_get` 能连麦蕊：lease → core 准入 → next_call → 窗口内 transport → complete。
- ② 位置：
  - `egress.py:448-546`（mairui_get）、`:394-445`（_admit）、`:225-273`（_https_get：先解析、登记 IP，再按 IP 建 TLS）
  - `daily_lists.py:190`（single_egress）、`:290`（调用 mairui_get）
  - 契约 §7.11.5 第 1、3、4 条
- ③ 请回答：
  - 整体是否仍有正常业务路径能不经 `mairui_get` 发出麦蕊请求（(a) 类）？
  - 拒绝码集合（:44-48 五个）是否完备、不泄露？
  - 「所有失败按 fail-closed」是否有遗漏分支？
- ④ 我方结论：fail-closed 矩阵每一行都有对应验收（A2–A27），先红后绿。拒绝日志不含证书和 URL（A16）。transport 计数断言见 A24。
- ⑤ 残余：见 R15、R19。另有 `DAILY_HTTP_LIMIT` 何时放开不在本方案范围（plan 未决 ③）。

### R13 TEMP 与 single-egress 锁
- ① 问题：临时证书文件的创建和 unlink 依赖「已持有 single-egress 锁」的前提。
- ② 位置：`daily_lists.py:88-128`（temporary、remove_owned）、`:238`、`:352`；契约 §7.11.5 第 4 节末「R13」段（plan :3793 起）。
- ③ 请回答：若锁前提失效（例如锁会话被服务端断开），TEMP 的竞争删除是否安全？非普通文件拒绝、残留普通文件替换的语义是否充分？
- ④ 我方结论：A14 覆盖时序、拒绝路径清理、HALT 不被清；A32 覆盖新交易日第二批次、0600 替换和清理、非普通文件 `temp_path_not_regular`。
- ⑤ 残余：锁会话中途丢失期间与另一实例竞争（单副本下不出现）。

### R14 检查与锁顺序、停机优先级
- ① 问题：顺序不得调换：HALT → lease → core → 证书准入 → next_call → HALT → 窗口 transport → 落库/HALT → complete。锁层级：single-egress 会话锁在最外层，ip_limit 事务锁在内层；不在事务内发 HTTP；HALT 与库内 upstream_halted 优先级最高，永不自动清除。
- ② 位置：`egress.py:469-546`；契约 §7.11.5 第 4、6 条（:1392、:1411）；plan :3793-3797。
- ③ 请回答：
  - 是否存在死锁或锁倒置？tick 只取 ip_limit 锁，是否确实无环？
  - HALT 是否可能被任何路径（user_reset、换证、重启）越过或清除？
- ④ 我方结论：A11（HALT 时不取锁、不访库）、A12（upstream_halted 不 rehydrate）、A15（tick/process 并发有界）已覆盖。解除 HALT 按 `deploy/runbooks/ingest-halt.md`，须用户本人确认。
- ⑤ 残余：无新增。

### R15 超时上界
- ① 问题：
  - 准入从进入 `mairui_get` 到决定 ≤3s（deadline=t0+2.8s 驱动 SET LOCAL；connect_timeout 2）；
  - lease 的 pg_locks 核验受同一 deadline 约束，并以短事务执行；
  - ⑦进窗再核用独立 0.5s 预算，不沿用准入 deadline。
- ② 位置：
  - `egress.py:51-52`（ADMIT_BUDGET_S、WINDOW_RECHECK_BUDGET_S）、`:156-197`（_conn_holds_single_egress：SET LOCAL、查完即 commit/rollback）、`:394-445`、`:505`
  - `core.py:153-190`；`src/backend/app/db/engine.py:36`
  - 契约 :1393-1397、:1384、:1385
- ③ 请回答：
  - 「建连 2s + 锁/语句 ≤0.8s」的上界推理是否成立？
  - ⑦的独立 0.5s 是否会让单次调用总时长超出某个外部约束？
  - 残余场景（库冻结但内核照常 ACK、PG 主机名解析阻塞、进程长暂停）下「准入未完成不放行」是否确实成立？
- ④ 我方结论：
  - A29：普通和 -O 各 10 轮，最大值 ≤3.0s，1 连接、1 次 xact lock；黑洞库 ≤3s 拒绝。
  - `src/backend/selfchecks/test_tb116e_m1_pg_locks.py`：transport 期间锁会话 state=idle。
  - B-4 用例：准入用时 2.65s 时仍能调用 transport。9435ad0 上为红，bda9694 上为绿。
- ⑤ 残余：契约 :1397 所列三种上限不成立的场景，表现为本批卡住、不放行，由心跳与健康检查告警。

### R16 静态守卫 S1–S6、S2b
- ① 问题：静态层只守一份有限清单，不再逐轮追加绕过写法；清单外的动态写法交给运行时层。
- ② 位置：契约 :1357-1364（S1 probes 冻结 24 文件；S2 egress 私有名；S2b netguard 窗口 API；S3 网络库导入及穷举例外；S4 麦蕊域名字面量；S5 transport 注入，唯一例外 daily_lists 测试缝；S6 动态导入登记）、:1377（①c 不负责项）；用例 `test_ta91_a1s_static_t_t55.py`、`src/backend/selfchecks/test_tb116d_a1s_static.py`。
- ③ 请回答：
  - 清单是否完整、无误报？
  - 登记例外（sources 的 urllib、workers/ingest 的 `socket.gethostname`、netguard、probes/selfchecks 动态导入登记）是否最小？
  - ①c 排除项是否都有运行时兜底？
  - S5 的 `**{"transport":…}` 字面量与 `**变量` 两种写法是否都已覆盖？
- ④ 我方结论：在 41e517a 上注入实测，S1–S4、S6 共 9 种违例都会红；S5 两种 `**` 写法在 T-T56 起补齐（团队评审记录 T-A92，未入库）。
- ⑤ 残余：通过 `sys.modules` 反射、`getattr` 拿到窗口 API 不在静态层范围（威胁模型外，见 R18）。

### R17 M-2 证书状态以库为准
- ① 问题：证书状态以库为准，upsert/rehydrate 不得把终态（INVALID/PAUSED_BY_ADMIN/EXPIRED）降回 active；上游 102 先落库为 INVALID，之后每次都拒 `licence_unavailable`；lease 不可伪造。
- ② 位置：`egress.py:349-375`（_row_active_licence）、`:298-347`（_persist_licence_status）、`:531-546`；契约 §7.11.5 第 2、4 条（:1380、:1398-1409）。
- ③ 请回答：重启、user_reset、换同值证书、内存 rehydrate 是否都不能自动恢复？内存与库不一致时是否一律取更严的一方？
- ④ 我方结论：A25（102 → INVALID，下一次和重启后都拒，transport 只 1 次）、A7、A6b。
- ⑤ 残余：见 R18 的双失败场景。

### R18 M-a lease 与 M-c 写库失败
- ① 问题：
  - **M-a**：lease 携带 nonce、thread_id、lock_pid、mac，其中 mac = HMAC-SHA256(进程内闭包密钥, 前三项)；核验包括 compare_digest、线程绑定、nonce 未释放、pg_locks 确认锁仍持有。往注册表塞假项不能放行。
  - **M-c**：102 或终态写库失败时，同时写 HALT（`licence_status_persist_failed`），本调用拒 `core_denied`，后续 `halt_present`；HALT 也写失败则 `os._exit(74)`；启动时停机目录不可写则返回 78。
- ② 位置：`egress.py:100-153`（_bind_lease_auth）、`:275-296`（_write_halt、_halt_or_die）、`:540-543`；`src/backend/app/workers/ingest.py:115`、`:167-185`（_probe_halt_directory）；契约 :1380-1387、:1401-1409。
- ③ 请回答：
  - 威胁模型边界（同进程任意代码执行在模型外）的表述是否诚实？
  - 「库写入与 HALT 写入同时失败、重启时两者都已恢复 → 至多再 1 次外呼」的残余能否接受？
  - 74/78 退出码约定是否与部署的重启策略相容？
- ④ 我方结论：
  - A28 四子例：塞注册表、replace mac/thread_id、跨线程、unlock 后对象仍在，全部 `single_egress_not_held`、transport 0 次。
  - A30：① HALT 内容与重启后 `halt_present`，② rc=74，③ rc=78 且不碰已有 HALT。
  - A26：首调 `core_denied`，后续 `halt_present`。
- ⑤ 残余：契约 :1405 所述双失败后重启至多再 1 次外呼；同进程读取闭包密钥、gc 遍历、ctypes 改内存在威胁模型外。

### R19 运行时层 netguard（`sys.addaudithook`）
- ① 问题：`main()` 第一行 `netguard.install()`（`workers/ingest.py:188`）安装不可卸载的审计钩子，规则如下：
  - 麦蕊 DNS 只在放行窗口内允许；
  - connect、connect_ex、sendto、sendmsg 的公网 IP 一律拒绝，除非处于窗口内且是本窗口已登记的 IP；非 IP 字面量的主机名一律拒绝；
  - 子进程全拒；
  - 安装前先 `import ctypes`；之后 dlopen（含 None）全拒，dlsym 只放 `Py`/`_Py` 前缀；
  - 开窗必须带 `validate`，lease 为 None 也拒；
  - 审计类别为封闭集合：mairui_dns、public_ip、hostname、subprocess、ctypes、lease。
- ② 位置：`netguard.py:101-155`（hook）、`:157-163`（install）、`:166-180`（egress_window）、`:182-193`（register_resolved_ip）；`egress.py:505`；契约 :1365-1376、:1377（①c）。
- ③ 请回答：
  - 有没有正常业务库在钩子下被误拦（(a) 类），例如 redis-py、psycopg、SQLAlchemy、uuid，或今后新增的依赖？
  - 契约承诺拦截的写法是否全部拦住（(b) 类）？
  - 公网默认拒绝会挡住 ingest 将来的其他合法公网出口（plan 未决 ④）。新增出口时的登记流程是否清楚？
- ④ 我方结论：
  - 无网容器探针在普通和 -O 下拦住全部 13 类：hostname、lease、ctypes、public_ip 等。
  - 正向放行项正常：回环、私网、AF_UNIX、`create_connection("localhost")`、`pythonapi.Py_*`、已登记窗口。
  - 装钩子后 redis-py 主机名连接、psycopg/SQLAlchemy 建连、uuid 都正常；`main()` 空跑无拦截记录（团队评审记录 T-A93、T-A94，未入库）。
  - 正式用例 A1r ①–⑬（`test_ta91_a1r_runtime_t_t55.py`）、自检 `test_tb116d_a1r_runtime.py`。
- ⑤ **对抗性残余（按收敛口径不阻塞，由 T-O68 容器网络层与本复核兜底）**：
  - ctypes 用裸地址构造函数指针（`ctypes.cast`）；
  - dlsym 放行的 `Py*` 符号（如 `PyRun_SimpleString`，执行的代码仍受钩子约束）；
  - 钩子安装前已建立的 socket 或已加载的扩展；
  - C 扩展直调 libc 的 connect/getaddrinfo（不触发审计事件）；
  - 篡改钩子闭包（gc、`__closure__`）；
  - ingest 之外的进程（worker、api、用户电脑上的 probes）。
  - 方案 B（compose 网络拆分）：运维 T-O68 已提交 ops/T-O68=896b6c0，T-O68b 修订为 ops/T-O68b=72d1f3a，**已随第 5 批合入 main=b6ba5f9**（团队评审记录 T-A96、T-A97，未入库）。后续 2cf67cf/d08b198（master-bootstrap、N4–N6 检查）尚未合入，待 T-O68c。要点：
    - 设计：`default` 和 `aia_internal` 都设 `internal: true`；只有 ingest 加挂 `aia_egress`；nginx 加挂 `aia_edge`（关闭 IP masquerade，只发布 127.0.0.1）。CI 守卫为 `scripts/ci/check_compose_networks.py`，用例在 `scripts/ci/tests/test_compose_networks.py`，运维说明在 `deploy/runbooks/networks.md`（以上路径均在该分支上）。
    - 与本节分工一致：方案 A（进程内 netguard）为主，B 为纵深、不阻塞后端。B 兜住了「ingest 以外的容器出网」和「新服务漏写 networks」两类。ingest 自身仍可全网出口，所以本节所列进程内对抗残余、ingest 的 DNS 外泄、同网横向移动，B 都兜不住，仍归 A 与本复核。
    - 阻塞项（守卫对正常写法漏拦）：覆盖层可以新声明一张非 internal 网络并把任意服务挂上去，守卫和 `docker compose config` 都放行。修法是覆盖层只许用四个登记网络名。
    - 登记项：
      - 守卫不检查端口发布地址必须为 127.0.0.1；
      - worker 主数据同步现为桩（`src/backend/app/workers/jobs.py:192-195`），解桩前须裁定由谁出网；
      - Docker Desktop 下 `enable_ip_masquerade=false` 未必能挡住 edge 出站（第三方报告），须在用户电脑上实测；
      - ~~`docs/plan.md` §T-A87 B 段和 T-O68 工作包写的是「预期 worker 也上 egress」~~：已按编排者 2026-11-09 裁定改写（`docs/plan.md` :3746、:3858、未决⑥ :3864）——worker、maint-cli 平时不出网，主数据同步解桩时优先放进 ingest，首导需联网用显式一次性 compose profile 接 `aia_egress`，SMTP/LLM 无功能不开，新增出网须经 R19 登记。
    - T-O68b（72d1f3a）复评：上述阻塞项已修（覆盖层只许四个登记网络名，另加端口必须绑 127.0.0.1 的检查，`deploy/runbooks/networks.md` 补了 ingest 全出口与 Docker Desktop/WSL 实测项）。新登记（对抗性，不阻塞）：`scripts/ci/check_compose_networks.py:134-160`（`_check_overlay_networks`）只查 internal 与 IP masquerade，覆盖层改写登记网络的 name/external/driver 会漏过，`docker compose config` 也通过：
      - N4：`aia_edge` 设 `external: true, name: bridge`，nginx 与 dev 的 postgres/redis 进入有 masquerade 的默认桥，可出网；
      - N5：改 `aia_edge` 的 `driver`（如 macvlan）；
      - N6：把 edge 或 internal 的 `name` 改成 egress 的网络名。
      - 建议运维加三行检查：覆盖层不得对已登记网络设置 `name`/`external`/`driver`。d08b198 已加此检查，**待 T-O68c 合入后重核本条**。
      - `deploy/runbooks/networks.md` 第 6 步（Docker Desktop 是否无视 `enable_ip_masquerade=false`、WSL mirrored）缺可执行命令和判定标准，例如在 nginx 容器内对公网地址做 5 秒超时请求、失败才算通过；第 2 步的 `${NGINX_HTTP_PORT:-8080}` 为 bash 写法，Windows 上须在 WSL/Git Bash 下执行或改用 `curl.exe`。文档改进，不阻塞。
    - T-A98 登记（评审 head=ops/T-O68b=d08b198；ops 文件行号按 d08b198，**待 T-O68c 合入后重核**）：
      - master-bootstrap 一次性首导服务运行期间挂 `aia_egress`，是全网出口，无 runtime netguard，仅靠代码只访问三所固定 https 地址。`src/backend/app/master/sources.py:545-548`（b6ba5f9 与 d08b198 行号相同）跟随 https 跳转时可到任意主机（只校验 `https://` 前缀）。该服务无麦蕊凭据，不涉及 M-1。缓解：显式一次性 profile、不常驻。建议后续限制跳转到白名单主机。
      - 守卫 `scripts/ci/check_compose_networks.py:47`（d08b198 的 `EGRESS_ALLOWLIST`；T-A98 所记 :45 为父提交 2cf67cf 行号）对 master-bootstrap 的例外只按服务名放行。去掉 profiles、`restart` 改 always、被 `depends_on`、加端口、覆盖层换 command 五种改法能通过。运维 T-O68c 以结构断言修复（待复评）。
      - 端口写法 `[::1]` 被守卫拒绝，偏严（误拦方向，非安全风险），记为已知限制。
    - 请复核方回答：B 是否还有正常部署会误走的出网路径？ingest 全出口这一事实是否已在运维文档中如实写明（建议 runbook 补一句）？
  - 已知行为（非缺陷）：Python 层 `connect(("localhost", …))` 会被按主机名拒绝；ingest 现无此写法。

---

## 5. B1–B4（T-A74 对 T-R35 待裁阈值的裁定）

共同来源：`docs/reviews/T-A74-rulings.md:43-46`（提交 docs/T-A74=d6e1580，已在 main）。依据：`docs/strategies/T-R35/README.md:67-71、:92-97`（b6ba5f9；该文件在 0e2e66c 已是 112 行，原引 :143-155、257-269 已失效），研究员维护，本包只引用不改。落地提交定位方法：只读的 `git log -S/--grep`、`git grep`，查 8b9f9f8（与 0e2e66c 在相关文件上无差异）。
- 研究员文档的落地：78e551a（T-R36，按 T-A74 定稿 T-R35，涉及 B1–B4）。
- 代码方面：裁定（d6e1580，2026-11-09 14:23 America/Denver）之后，没有找到专门落实 B1–B4 的后端或测试提交。各条情况分述于下。

### B1 发布资格窗
- ① 问题：「统一 20 日复盘窗」与 T+1/5/20 多跟踪期并存。
- ② 位置：`docs/reviews/T-A74-rulings.md:43`；`docs/api-contract.md:1277`（交易日历口径）；`docs/plan.md:963`、`:784`。
- ③ 请回答：「n_映射≥20 或 模拟交易日≥20，且 verified_live 与管理员批准缺一不可；日历缺日不计天」作为发布门槛是否合理？
- ④ 我方结论：采纳并补充。「统一 20 日」只指发布资格窗，报表三列照出。
- 落地：**未定位**。`src/backend/app` 中没有找到按「n_映射≥20 或 模拟交易日≥20」判定发布资格的代码；晋级 published 现在仍硬拒，返回 `PROMOTION_GATES_NOT_MET`（`src/backend/app/strategy/reviews.py:425-431`），与同文 B5「本期不做」一致。
- ⑤ 残余：资格计数实现与用例都未落地，要等 B5 立项。

### B2 缺 horizon 不进 n
- ① 问题：H-01 多周期样本如何计入 n。
- ② 位置：`docs/reviews/T-A74-rulings.md:44`；同文 §1（H-01 不拆版本）。
- ③ 请回答：比原建议（只不进胜率）更严，是否会让样本长期不足？
- ④ 我方结论：采纳并加严，只计 gap 并展示；理由是不进胜率却进 n 会抬高样本量、提前达到 n≥20。
- 落地：**部分定位**。RC5 模拟失败计数中，缺 horizon 只记 gap `sim_fail_horizon_unknown`，不进入计数（`src/backend/app/feedback/core.py:103-108`）。这是裁定前就有的行为，来自 8219665（P2N-08 slice1）；定点用例 28c3e7d `tests/backend/unit/test_tb113_l1_l10_runner_h12_h17_t_t46.py::test_tb113_h17_missing_horizon_is_gap_not_counted`，自检 52d3bee `src/backend/selfchecks/test_tb113_h17_horizon_gap.py`。发布资格 n 的计数实现**未定位**（同 B1）。
- ⑤ 残余：发布资格 n 落地时需要同一口径的用例。

### B3 G6 warn 语义
- ① 问题：G6 warn 是否计入「模拟健康」否决。
- ② 位置：`docs/reviews/T-A74-rulings.md:45`；`src/backend/app/strategy/reviews.py:467-475`（行号按 8e847d5）；`docs/plan.md:790-796`。
- ③ 请回答：warn 经 ack 后不挡信号、不降权、不等同 verified_live，门禁语义是否过松？
- ④ 我方结论：采纳；代码只要求 warn 被确认。
- 落地：现状即裁定口径，无需新提交。`ack_warn_gates` 校验见 `src/backend/app/strategy/reviews.py:292-310、375`（0e2e66c；来自 c6ce767 T-B83、5a960e2 T-B83b，均早于裁定）。裁定后专门锁定「不挡信号、不降权」的用例**未定位**。
- ⑤ 残余：缺上述锁定用例；行号要按最终 main 复核。

### B4 S-01 主口径
- ① 问题：S-01 发布观察取满 20 日还是 T+5。
- ② 位置：`docs/reviews/T-A74-rulings.md:46`；`docs/strategies/cards/st_pullback_ma.md:32`；`docs/api-contract.md:1280`。
- ③ 请回答：以 T+5 为主口径、资格计数取 T+5 complete 是否合理？
- ④ 我方结论：裁定。与 RC5 short→5 一致，不用 20 日替代 5 日。
- 落地：**未定位**。`src/backend/app` 与前端中没有找到「T+5 主口径」高亮或按 T+5 complete 计数的实现。
- ⑤ 残余：实现与用例都未落地。

---

## 6. 「待补」与未定位清单
1. B1、B4：落地代码与用例**未定位**。B2 只定位到 RC5 侧；B3 的锁定用例**未定位**。
2. R6：G1–G5 边界缺用例（见 R6 表）。
3. R4：只做了列名匹配加人工判读，未在库内用 pg_catalog 全量核对。
4. 行号已按 main=b6ba5f9 复核（T-A99，含 `netguard.py` 与 `docs/plan.md` +4 修正）；main 再变动时须重核。
5. `docs/reviews/T-A76-tb110-review.md` 的勘误行已随本文同一提交加入（文字见 §1 编号冲突段）。

## 7. 复核方交付建议
逐项给出：同意 / 不同意 / 需补证据；对不同意项标 (a)、(b) 或对抗性残余，并给出复现步骤。复现只允许用假 transport、一次性无网数据库、无网容器，**禁止**对麦蕊任何域名发真实请求。
