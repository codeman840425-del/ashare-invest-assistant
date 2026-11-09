# T-A72 0030 迁移待办（M1–M6，承接 T-A70 评审）

> 架构师，2026-11-09（America/Denver）。依据：docs/reviews/T-A70-tb99e-0029-review.md 第 2 节；行号按 be/T-B109 头 6d622a9 上的 `src/backend/migrations/versions/0029_tb99e_gate_bindings.py`（下称 0029，blob 05774fe，与用户库已执行版一致）。ingest 调用方行号按 tb-T-B99e 8c5746b（门控应用代码本轮未吸收，仅作上下文）。
> 状态：待办，未派单实现；本文不改 src/tests/deploy。

## 0. 总约束（所有项适用）

1. 0030 的 `down_revision` 必须是 `"0029"`，链保持 …→0028→0029→0030 线性单 head。
2. **不得改动 0029 文件本身**（用户库已执行；blob 必须保持 05774fe），一切修正只能放进 0030 或之后的迁移。
3. 0030 必须对用户库现状幂等可执行：库里已有绑定行与 scope 行（T-O45），不得为迁移删除或改写既有事实行。
4. 0030 的 downgrade 回到 0029 时不得丢事实；做不到就像 0029 一样有数据即拒绝，并在契约里写明。
5. 授权口径以 T-O57（c01a3d0）为准：只有 aia_ingest 可访问 `ingest_private`，aia_api、aia_maint 不得获授；新对象同样只授 aia_ingest，跨角色需要的动作一律走 `SECURITY DEFINER` + `SET search_path=pg_catalog` 的窄函数。
6. 0030 与门控应用代码（T-B99 基座）一起吸收时再派单；在此之前 0029 保持休眠，不提前写 0030。
7. 验收统一在隔离 PG、只用合成数据：空库 0028→0029→0030→0029→0030 往返 `pg_dump -s` 一致；用「已有绑定和 scope 行」的 0029 库升到 0030 成功且行数、定义符合预期；tb95 全绿；`migration_check` 输出 `0030 (single mainline head)`；verify-roles 的 T-O57 反例全部通过；全程真实麦蕊调用为 0。

## 1. 已接受的设计（不改）

| # | 问题（文件:行号） | 裁定 |
|---|---|---|
| M1 | 0029:85-92：scopes 或 bindings 任一非空，downgrade 抛 `mairui_gate_facts_require_authorized_archive` 拒绝；0029:78 aia_ingest 对 scopes 无 DELETE，scope 行无删除路径 → 用过即不可降级 | **接受为设计**：拒绝降级、不丢事实是正确的数据安全取舍。契约 §7.11.2 T-A52 第 9 条已改为「库保持 0029，不降 0028」。**遗留待办 M1-a**：错误信息中的「authorized archive」路径在仓库里不存在。目标：若将来确需降级或清理，另写归档脚本（导出到受控备份、校验 sha256、再删），经架构师评审并由用户本人批准后才可执行；在它存在之前，任何人不得以删行方式绕过守卫。负责：架构师（方案）→ 后端（脚本）→ 运维（演练）→ 测试（验收）。验收：在恢复演练副本上，归档文件可完整还原被删行；未批准时脚本默认 dry-run |

## 2. 0030 待办

| # | 级别 | 问题（文件:行号） | 目标 | 验收标准 | 负责角色 |
|---|---|---|---|---|---|
| M2 | 中 | 0029:41-47：`prune` 的 UPDATE 无 `detached_at IS NULL` 过滤，每次调用重写**全部** scope 行（COALESCE 不能免除行重写，会产生新元组和 WAL）；scope 只增不删（0029:78），写放大随时间单调增长 | 0030 用 `CREATE OR REPLACE FUNCTION` 重定义 prune：UPDATE 只作用于 `detached_at IS NULL` 的行；为 scope 定保留期（与 M1-a 归档方案一并定，不在 0030 里物理删行，除非归档方案已批准） | 合成库造 N 条已 detached 的 scope，调用 prune 前后这些行的 `xmin` 不变；未 detached 且无有效绑定的行被置 `detached_at`；有有效绑定的行不变；函数仍是 SECURITY DEFINER、`search_path=pg_catalog`、EXECUTE 只授 aia_ingest | 后端（迁移）、测试（用例）、架构师（评审） |
| M3 | 中 | 0029:51-72（触发器在 `user_data_licences` 的 `deleted_at/paused_until/status` 任一变化时执行，0029:69-72），0029:65 每次触发都跑全表 prune；ingest 每个事务也跑一次（8c5746b:src/backend/app/ingest/certificate_bindings.py:81-82、104）。api（改证书状态）与 ingest 两个角色的事务对同一批 scope 行加行锁，写放大并互相等锁 | 0030 拆出按范围的 prune：触发器只处理 `NEW.id/OLD.id` 涉及的绑定和其 scope（例如 `prune_mairui_gate_scope(scope_id)`）；全表 prune 只留给 ingest 的定时/低频路径；触发条件收窄为相关列真的变化（`WHEN (OLD.* IS DISTINCT FROM NEW.*)` 针对三列） | 两会话并发测试：会话 A 以 api 身份更新证书 1 状态、会话 B 以 aia_ingest 处理证书 2，互不阻塞（`pg_locks` 无相互等待）；更新证书 1 时只触及其 scope 行；status 未变的 UPDATE 不触发 | 后端（迁移+调用方）、测试（并发用例）、架构师（评审） |
| M5 | 低 | 0029:57-63：CASE 先判 `paused_until`（0029:59），ip_limited 冷却只暂停 120 秒时绑定只保留 120 秒，24 小时分支（0029:60-61）走不到；删除后重新添加证书即可绕过 docs/plan.md:406「1 小时内 3 次 → 暂停 1 小时」的升级规则。不违背契约第 28 条「最多 24 小时」（docs/api-contract.md:47） | 0030 改为：status 为 `ip_limited/quota_exceeded` 时取 `GREATEST(NEW.paused_until, NEW.deleted_at + interval '24 hours')`，其余情况保持原逻辑，仍外包 `LEAST(COALESCE(expires_at,'infinity'), …)`；保留期上限是否 24 小时由产品口径确认（架构师提请用户） | 合成用例：ip_limited + paused_until=删除后 120 秒 → expires_at = deleted_at+24h；quota_exceeded 同；正常状态删除 → expires_at=deleted_at；已有更早 expires_at 时不被延长；「删除→重加」后 1 小时内第 3 次限流仍升级为 1 小时暂停 | 后端（迁移）、测试（用例）、架构师（产品口径确认） |
| M6 | 低 | 0029:14-18：scope 只存 `origin_licence_id`，无外键；绑定随用户删除级联消失（0029:21），scope 行留下成孤儿。用户删除 CLI 走 aia_maint（docs/plan.md:263），而 T-O57 规定 aia_maint 无 `ingest_private` 权限，所以 CLI 也删不到 | 0030 提供清理路径二选一（架构师在派单时定）：① `app.users` 删除时由 SECURITY DEFINER 触发器清理该用户来源的 scope（需先解决 M1-a 的归档口径）；② 提供只授 aia_maint EXECUTE 的窄函数 `ingest_private.purge_user_scopes(user_id)`，由用户删除 CLI 调用，不给 aia_maint 任何表权限 | 合成用户删除后，`ingest_private` 中无以其证书为来源的 scope；verify-roles 的 T-O57 反例（aia_maint 无 USAGE/表权限）仍通过；用户删除 CLI 的回归用例覆盖该步骤 | 后端（迁移+CLI）、运维（grants/verify-roles 只增函数授权）、测试（用例）、架构师（评审） |

M4（grants 排除 `ingest_private`）已由 T-O57（c01a3d0）处理，不进 0030。M7 无需处理。
