# T-A75 限流升级规则可被绕过：最小修法方案

> 架构师，2026-11-09（America/Denver）。基线 origin/main 8e847d5。文中 `文件:行号` 均以 8e847d5 为准，`state.py`、`core.py` 指 `src/backend/app/ingest/` 下同名文件。
> **风控，需另一个模型复核**（整份方案，尤其 §3 计数键与 §4 的 fail-closed 口径）。
> 状态：草案，未派单实现；本文只改 docs，不改 src/tests/deploy。排在 M6（0030，后端 T-B110，见 docs/T-A73 分支 `docs/reviews/T-A73-0030-plan.md`）之后，与 0029/0030 无依赖。

## 0. 结论

- 选定方案 A：**计数键改为 `user_id`，持久化复用现有只追加表 `ops.data_licence_events`，不需要迁移**。同一处修改同时堵住「删掉后重加」和「重启」两条路径，另外顺带堵住「点测试/重新 PUT 清暂停」。
- 任务数：后端 4、测试 6、运维 2（§5）。
- 严重度：**潜在，未上线**。主线的 ingest 入口目前不调用 `IngestCore`（见 §1.3），但 `IngestCore` 一旦接进外呼循环，这个漏洞就会直接上线。所以本修复必须在接线之前或与接线同一批合入。

## 1. 现状核实（行号已逐条核对）

### 1.1 三样东西分别存在哪里

| 项 | 位置 | 生命周期 |
|---|---|---|
| 升级计数 `ip_limited_hits` | `state.py:66`，`deque`，只在 ingest 内存 | 跟 `LicenceState` 走；`LicenceState` 挂在 `IngestCore.licences[licence_id]`（`core.py:43`） |
| 计数逻辑 | `state.py:148-165`：先丢掉窗口外的命中（150-152），追加本次（153），达到 `count` 后清空并暂停 `pause_s`（154-163），否则暂停 `ip_limited_pause_s`（164-165） | 同上 |
| 暂停 `paused_until` | 内存：`state.py:63`；库：`app.user_data_licences.paused_until`（`db/tables/licences.py:77`）；删除时处于冷却会写入 `app.user_data_licence_cooldowns`（`licences.py:129-152`，迁移 0012） | 库中这一列只由 api 写；主线没有任何 ingest 代码把内存状态写回库 |
| 参数 | `config/ingest.yaml:51-52`：`ip_limited_pause_s: 120`，`ip_limited_escalate: {count: 3, window_s: 3600, pause_s: 3600}` | — |

### 1.2 两条绕过路径（已复现，纯内存，未起 PG、未发任何外部请求）

在 8e847d5 上用 `IngestCore` 和真实的 `config/ingest.yaml` 跑了三组：

- 基线：同一 id 在 0、5、10 分钟各命中 1 次 → 第 3 次触发 `ip_limited_escalated`。
- **删掉后重加**：id A 命中 2 次 → `remove(A)`（`core.py:78-80`）→ `upsert(B)`。新 id 走 `core.py:68-73`，得到全新的 `LicenceState`。第 3 次命中只触发 `ip_limited`，计数为 1。api 侧的冷却恢复（`licences/service.py:373-385`、`409-415`）只恢复 `status`、`paused_until`、`last_error_*`、`consecutive_failures`，没有计数，因为计数根本不在库里。
- **重启**：命中 2 次 → 新建 `IngestCore` 并 `upsert` 同一 id → 第 3 次命中不升级，只暂停 120 秒。附带问题：`upsert` 没有 `paused_until` 参数（`core.py:58-76`），重启后连库里的暂停截止时刻也接不上。

第三条同源路径：`user_reset()`（`state.py:199-205`，用户重新 PUT 或点“测试”时调用）会把 `paused_until` 清空。升级后的 1 小时暂停也能这样清掉。

### 1.3 规则定义与实际接线

- plan.md:406：「103 / HTTP 429（IP 超限）→ `ip_limited`，暂停 120 秒；1 小时内 3 次 → 暂停 1 小时，并通知用户（“证书可能正在别处使用”）和管理员」。plan.md:196、2329 写明，103 的含义是同一证书 60 秒内超过 2 个来源 IP。
- api-contract.md:1405（v0.2.6 验收）的口径与 plan 相同。api-contract.md:79（#13）、831、833 只规定 DELETE 后再 PUT **同一证书** 时恢复 `status` 和 `paused_until`，换证照常验证，没有提到升级计数。
- 接线现状：`workers/ingest.py:86-106` 只跑 `daily_lists.tick`，没有任何生产代码实例化 `IngestCore`（`core.py:3-9` 注明「外呼循环（后续任务）」）。`daily_lists.py:269-294` 第一次遇到 103/429 就写 HALT 文件并停机，比「3 次」更严。
- 相关风险，不在本方案范围内：HALT 文件位于 `/run/aia`（`daily_lists.py:45`），compose 没有为它挂卷，容器重建后文件就没了，同样是「重启清零」。建议编排者另立一项，交运维评估。

## 2. 备选方案对比

| 方案 | 计数键 | 存储 | 删掉后重加 | 重启 | 迁移 | 主要缺点 |
|---|---|---|---|---|---|---|
| **A（选定）** | `user_id` | 复用 `ops.data_licence_events`（只追加，0007:62-63 触发器拒绝 UPDATE/DELETE） | 堵住（同一或不同证书都是同一用户） | 堵住（启动时按库回填） | **不需要** | 按用户算比按证书严：换一张证书也继承计数；`user_id` 列没有索引，但这张表很小 |
| B | `user_id` | Redis（有序集合加截止时刻键） | 堵住 | 只防 ingest 重启；Redis 重启、淘汰或 flush 后清零 | 不需要 | 不持久；违反契约 #32 ①「冷却按数据库 UTC 时间比较」的口径 |
| C | `user_id` | 0031 新表 `ingest_private.ip_limit_escalations(user_id PK, hits timestamptz[], escalated_until)` | 堵住 | 堵住 | 需要（0031，down_revision=0030） | 多一张表、一套 grants（T-O57 白名单要扩）；downgrade 有数据时必须拒绝，又会碰上 M1-a 的归档问题。不必要 |
| D | 证书指纹 | 任意 | 只对同一证书有效 | 视存储而定 | 视存储而定 | **会泄露**，见 §3 |

## 3. 计数键：为什么用 `user_id`，不用证书指纹

- `user_id` 不来自任何密钥材料，存进事件表不增加泄露面。每个用户最多一行未删除的证书（`licences.py:102-107` 部分唯一索引），所以按用户计数在正常使用时就等于按「当前证书」计数。
- 证书指纹在这里都不能用：
  - ingest 不得持有 `APP_MASTER_KEY`（`config.py:68`；`workers/ingest.py:42-47`），算不出带密钥的 HMAC。
  - 如果改用不带密钥的哈希，那就是一个稳定的、由证书推出来的标识。拿到库的人可以离线验证猜到或泄露的证书，还能跨账号关联。这就是泄露。
  - 现成的带密钥值也不行：去重 HMAC `licence_hmac` 删除时置 NULL（`licences.py:96-99` 约束 `deleted_wiped`）。冷却指纹只在冷却中删除时才写，到期即删，归 api 管（`seal.py:13-18`、`licences/service.py:286-308`）。两者都不能跨删除、跨重启地充当计数键。要保留它们就得改约束和契约，违反「不存可用于识别证书的值」的原则。
- 上游账户 ID：我们拿不到（麦蕊不返回）。
- 换证也继承计数的代价：103 说明这个用户的部署有多 IP 使用的问题，换证不能证明问题已经消失。所以按用户计数是更保守、也更符合风控方向的选择。这一点**需另一个模型复核**。

## 4. 选定方案 A 的设计

1. **写**：ingest 处理一次 IP_LIMITED 结果时，在同一个数据库事务里依次做三件事：
   - 先取 `pg_advisory_xact_lock(hashtext('ingest:ip_limit:' || user_id))`。
   - 写一行 `ops.data_licence_events`：`event='ip_limited'`、`actor='ingest'`、`to_status='ip_limited'`、`upstream_code` 为 `'103'` 或 `'429'`，`at` 用库的默认 `now()`。复用 `licences/service.py:155-176` 的 `record_event`。
   - 如果这次构成升级，再写一行**升级标记**：`event='paused'`、`actor='ingest'`、`to_status='ip_limited'`。这三个值都在现有 CHECK 白名单里（`licences.py:43-56`）。主线上 `paused` 只有 `actor='admin'` 用过（`api/v1/data_licence.py:387`），所以不会和管理员暂停混淆。
2. **算**（数据库 UTC 时间）：
   - `last_mark` = 该用户最近一条升级标记的 `at`。
   - 计数 = 该用户 `actor='ingest' AND event='ip_limited'`、`at >= now() - window_s`、且 `at > last_mark` 的行数。这对应 `state.py:155` 的「升级后清零」；保留 `at == now() - window_s` 的命中，与 `state.py:151` 的 `<` 一致。
   - 用户级升级暂停截止 = `last_mark + pause_s`。
3. **用**：`IngestCore` 改成按 `user_id` 保存命中队列和升级截止时刻，`licence_id → user_id` 另存一张映射。下面三个时点都从库回填：
   - ingest 启动时；
   - `upsert` 遇到新 id 时；
   - `user_reset` 时。

   每张证书的有效 `paused_until` 取「本行暂停」与「用户级升级截止」两者中较晚的一个。`user_reset` 和 `tick` 不得把它提前。
4. **fail-closed**：事件写入失败或回填查询失败时，按「已升级」处理：该用户在 `pause_s` 内不放行，下一轮重试写入。不允许在没有持久化的情况下继续外呼。
5. **不改的部分**：
   - 120 秒单次暂停仍按证书行处理，契约 #13 原样保留；
   - 通知仍由 `Transition.notify_*` 触发（`state.py:157-163`）；
   - 不写证书行的状态回写，那属于外呼循环接线任务，plan.md:2544 已有约定。
6. **迁移：不需要**。只用现有表、现有列、现有枚举值；ingest 对 `ops` 已有 SELECT/INSERT（`deploy/db/roles/grants.sql:103-111` 通配授权，`ingest_private` 已被排除在外）；不碰 `ingest_private`，aia_api 和 aia_maint 仍不得获授它（grants.sql:145-181，T-O57）。运行时没有 DDL 和表锁；每次命中只有一次 INSERT，加一把按用户的事务级咨询锁。
   - **后备**：只有当实测回填查询过慢时才做 0031（down_revision="0030"）：`CREATE INDEX CONCURRENTLY ... ON ops.data_licence_events (user_id, at DESC) WHERE actor = 'ingest'`。它要放在 alembic 的 autocommit 块里执行，只取 SHARE UPDATE EXCLUSIVE 锁，不阻塞读写。downgrade 用 `DROP INDEX CONCURRENTLY`，不删数据，也不涉及 grants。默认不做。
7. **账号删除**：CLI 会把事件行的 `user_id` 置 NULL（`cli/delete_user_data.py:142`），账号随之删除，计数自然作废，与 plan 7.3 一致。

## 5. 原子任务与验收

| 角色 | # | 任务（一句话） | 验收标准（可执行） |
|---|---|---|---|
| 后端 | B1 | `IngestCore.upsert` 增加必填 `user_id`，把命中队列和升级截止时刻从 `LicenceState` 移到 `IngestCore` 按 `user_id` 保存 | 单测：同一用户的 id A、B 交替命中 3 次（1 小时内）→ 第 3 次返回 `ip_limited_escalated` |
| 后端 | B2 | 每次 IP_LIMITED 在一个事务内按 §4.1 取咨询锁、写命中事件，升级时再写标记 | 合成库上命中 3 次后，该用户有 3 条 `ip_limited/ingest` 和 1 条 `paused/ingest/ip_limited` |
| 后端 | B3 | 新增 `rehydrate(conn, user_id)`，按 §4.2 从库回填，在启动、新 id `upsert`、`user_reset` 时调用 | 单测：库中已有 2 次命中，新建 `IngestCore` 回填后再命中 1 次 → 升级，截止 = 第 3 次的 `at` + 3600 秒 |
| 后端 | B4 | `user_reset`、`tick`、`allows` 以「本行暂停与用户级截止取较晚者」为准；写库失败时按 §4.4 fail-closed | 单测：升级后调用 `user_reset()`，`allows(..., verify=True)` 在截止前为 False；模拟写入异常时为 False |
| 测试 | T1 | **删掉后重加（先红后绿）**：A 命中 2 次 → remove(A) → upsert(B, 同用户) → 第 3 次 | 在 8e847d5 上断言 `ip_limited_escalated` **失败**（实际 `['ip_limited']`，计数 1）；修复后通过 |
| 测试 | T2 | **重启（先红后绿）**：一次性无网络 PG 合成库写 2 次命中 → 丢弃 `IngestCore` 重建并回填 → 第 3 次 | 修复前断言升级**失败**；修复后通过，且截止 = 第 3 次 + 3600 秒 |
| 测试 | T3 | 换证与“测试”：升级暂停期内 PUT 不同证书或调用 `user_reset` | 截止前该用户的任何 id 都不外呼、不验证；截止后才放行验证 |
| 测试 | T4 | 边界与隔离：`at == now-3600` 计入；标记之后的命中从 1 重新计；用户 A 的命中不影响用户 B | 三条断言全部通过 |
| 测试 | T5 | 不泄露：对新事件行和 ingest 日志做测试证书子串扫描（≥4 位，沿用 api-contract.md:1402 口径） | 扫描零命中；事件行没有指纹、HMAC 或证书片段列 |
| 测试 | T6 | 记录 fail-closed：让事件 INSERT 抛错 | 该用户在 `pause_s` 内外呼次数为 0 |
| 运维 | O1 | `verify-roles.sh` 补断言：aia_ingest 对 `ops.data_licence_events` 有 SELECT、INSERT，aia_api 和 aia_maint 仍无 `ingest_private` 权限 | 在合成库上 `verify-roles.sh` 退出码为 0；手工撤掉 aia_ingest 的 INSERT 后退出码非 0 |
| 运维 | O2 | `deploy/runbooks/database.md` 补一句（plan.md:278 提到的 `ingest-failover.md` 主线上还不存在，不为此新建）：重启或换机后升级暂停由库自动恢复，不需要人工处理；严禁手工清理 `ops.data_licence_events` | `rg -n "T-A75" deploy/runbooks/database.md` 有一行 |

## 6. 契约改动

只在 `docs/api-contract.md` v0.2.6 验收的「回放模式」条目后加一条子项，标「草案（T-A75）」。plan.md 不改，等复核通过后再同步。
