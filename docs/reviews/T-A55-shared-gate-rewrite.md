# T-A55 评估与裁定：共享门禁/冷却/验证链停止补丁循环，按 DB 单一事实源重写（架构师，北京 2026-11-10）

> 结论：**A 重写**。冻结 T-B99b–T-B99j，不把 e8ffe05 合入 team-b；名单链继续暂停，探针 T-B05/T-B86 的授权时段、128 台账、STOP 与调用次数不变。本文不定实跑日期，真实调用仍另等 Chief 派单。
> 评估范围：T-B99 及 b–j 报告、相关 diff（重点 c1a1cbd、3322aff、d85e660、9aa119f、585e9fc、1be0311、5669cb1、5e744c2、e8ffe05）、RV-14 四项 P1 摘要；只读评审，未跑测试、未外呼。
> DeepSeek：未用，原因：架构与安全裁定不外包。

## 1. 判定：设计层纠缠，不是四个可独立修完的边角

### 1.1 四套事实源，状态语义互相覆盖

| 事实 | 当前承载 | 纠缠表现 |
|---|---|---|
| 证书/冷却绑定 | DB 业务行、私有 tag/随机 scope、曾有的 SQLite/文件映射 | DELETE/换证/同证重设时，UUID、指纹、scope 生命周期不一致；十轮中多次改 0029 触发器 |
| 停机 | 公共 STOP、文件闩锁、DB 冷却、探针台账 | A 的孤儿子记录曾阻断 B；文件已落闩而 DB 回滚、或 DB 已暂停而文件未落闩，形成相反半态 |
| 验证投递 | 原审计流、v1/v2/逐 UUID 组、实时/回填索引、DB pending 代次 | ACK 组发现、历史回填、重复投递和注销清理互相依赖；修一个组又出现另一个组的漏认 |
| 外呼临界区 | POSIX flock、PG 用户锁、receipt、Redis 暂停、业务状态 | 锁顺序与覆盖边界随补丁增加，发送、DELETE、PUT、purge、ACK 仍出现新交错 |

### 1.2 四类 P1 是同一根因的不同投影

1. **空截止冷却永久残留 vs 契约 24h**：e8ffe05 直接删除 `COOLDOWN_NULL_UNTIL_TTL` 和 purge 分支，把上游「无自动恢复时刻」误等同为「删除后指纹可永久保留」。这是把运行状态与隐私保留期混成一态。
2. **超限体/嵌套信封判定不完备**：纯文本、顶层标量、显式 error 递归、JSON 数值、前导空白、流式分块各有补丁，且 `limit_code` 与 `upstream.classify` 曾分叉。缺少一个完整文法和唯一出口，不是在现有函数后再加两个正则就能证明完备。
3. **历史 ACK 组漏认**：Redis 同时被当队列、索引和 ACK 事实源，DB 又另有请求日志；跨组重建索引必然带来「已 ACK 是否还该投」的二次判定。
4. **注销—投递竞态复活**：扫描、加锁、Lua 写索引、注销删库、提交后清 Redis 不是一个原子协议；再补一把用户锁只能覆盖已知交错，不能证明所有旧消息来源都被围栏。

### 1.3 为什么不再选「最后一轮」

- b–j 每轮都同时改生产代码、迁移、权限、存储兼容与数百行测试；最近七轮约数千行变更，RV 后仍出现同类 P1。
- 0029 在未部署分支中被连续改写，说明状态模型尚未稳定；继续改只会扩大兼容矩阵。
- 当前尚未合入 team-b、未部署、未实跑，正是丢弃错误抽象成本最低的时候。

## 2. 重写目标架构：DB 是唯一业务事实源，Redis 只做唤醒，文件只留公共 STOP

### 2.1 必须删除的复杂度

- 删除 `verification_index` 的实时/回填双索引、跨 consumer-group ACK 推断和 Lua 路由；**不自动消费历史 Redis 验证消息**。
- 删除私有 SQLite/文件证书绑定与按证书文件闩锁；绑定、冷却、停机、预留、结果全部以 DB 为准。
- 不再让 `limit_code`、`upstream.classify`、探针各自识别 103/429；只保留一个响应判定入口。
- 保留：HPKE 解封边界、receipt、名单 3 次预算、POSIX 单出口发送锁、公共 STOP、128 探针台账、审计/通知去重、RLS 与角色负例。

### 2.2 验证改为 DB outbox（注销/ACK 的原语级解法）

复用 `ops.ingest_request_log`（或等价单表，实施时只选一个，不再双写）作验证 outbox：

1. API 的 PUT `/me/data-licence` 在**同一 DB 事务**写入业务行和 `queued` 验证记录（`verification_id, licence_id, user_id, binding_generation, requested_at`）；事务提交后才可发 Redis 提示。Redis 消息只含 `verification_id`，不含证书，也不代表可执行授权。
2. ingest 以 `SELECT … FOR UPDATE SKIP LOCKED` 认领 DB `queued` 行；Redis 只触发它去查 DB。没有 Redis 时，DB 周期扫描仍能完成；没有历史 Redis 回填这个子系统。
3. 发送前按「用户控制锁 → 校验 live 绑定和 generation → 预留请求 → 解封 → 实际 HTTP」一个顺序执行；`verification_id` 全链路唯一，重复消息/重启只读既有预留，结果不确定永不重放。
4. 注销指 `delete_user_data/purge`（不是退出登录）：purge 与投递/认领使用同一用户控制锁，在 DB 内先把相关 outbox 置 `cancelled` 并围栏 generation，再删授权数据；提交后清 Redis 提示只是整理，不是正确性前提。
5. 若 purge 先赢：认领/回填查询看不到可执行行，HTTP=0；若发送先赢：该次已发请求计账，purge 等临界区结束，结果只能写审计，**不得**按旧 generation 更新新绑定或把状态复活。
6. 切换顺序：先升级 API 为 DB outbox 写入，再升级 ingest；旧 Redis 流保持不消费，由运维核对旧 pending 后归档。禁止「旧流自动重放 + 新 outbox」双执行。

### 2.3 三个正交生命周期（不是把三者合成一个枚举）

#### A. 绑定 `binding`

`live(scope_id, licence_id, user_id, fingerprint, generation)` → `detached(scope_id, fingerprint, retention_deadline)` → `expired/purged`。

- `scope_id` 是 API 在首次绑定时生成的随机非秘密标识，DB 保存；ingest 不需要 APP_MASTER_KEY，也不读证书明文/HMAC。
- 同用户、同指纹在有效冷却期内重绑，复用原 scope 与停机事实；不同指纹永远新 scope，旧事实不转移。
- 绑定关系、generation、冷却期限全部 DB 事务变更；不再有文件/SQLite 副本。

#### B. 冷却 `cooldown`

`none → bound_cooling → detached_cooling → expired/purged`，按 `(user_id, fingerprint)` 独立存在。

- `bound_cooling`：证书行仍 live，`paused_until=NULL` 的 `ip_limited/quota_exceeded` 可无限期阻止该证书自动外呼；24h 不适用于未删除的绑定。
- `detached_cooling`：DELETE/替换后开始保留期。`paused_until` 非空 → 保留到该时刻；为空 → **保留到首次真实 DELETE/替换后 24 小时**。到期为半开区间终点，`now >= deadline` 即不可恢复；重复 hold/PUT/DELETE 不续期。
- 同证在期限内重绑 → 恢复原上游状态和 scope；逾期/换证 → 新验证。审计和匿名 scope 事实可按安全需要另存，但不得作为恢复指纹或阻断其他证书的依据。
- 管理员 hold 本身不是 cooldown。若 hold 前已有真实上游冷却，独立保留原快照与期限；纯 hold 不创建指纹/24h tombstone。

#### C. 暂停 `pause`

`none ↔ admin_held`，是用户级独立状态，优先于验证和所有产品外呼；DELETE/PUT 不清除，只有管理员 resume 解除。全局 ingest paused 与公共 STOP 仍另作全局控制，不进入证书冷却状态机。

### 2.4 限流识别唯一入口与完整文法

新增唯一纯判定模块（名称由后端定），所有名单、验证、T-B05、T-B86 与 `upstream.classify` 只能调用它；传输层只负责按 4 KiB 分块提供字节，不再各自解释错误。

1. HTTP 103/429 直接判限流；HTTP 103/429 不需要读 body。
2. JSON 只接受根对象：顶层 `code/error_code/status` 标量，以及显式 `error` 标量或 `error` 对象递归；`error.code/status` 同规则。整数语义的 `103.0/429.0` 可接受；**不遍历** `data/items` 或数组业务行。
3. 纯文本去前导 JSON 空白后，只认完整 `103/429` 或 `103:/429:`（含中文冒号）前缀；`103.0`、`103元`、财务字段和普通文本不误判。
4. 流式读取不保存前导空白；首个有效字符后最多取 64 KiB 用于文法判定。JSON 不完整、未知形态、超限仍不能判定 → `unknown_upstream`，保留未知在途并停止后续调用，**不得当 OK，也不得伪造 `ip_limited`**。普通成功 body 的 16 MiB 存储上限与判定分流，不能靠无限读尾证明安全。
5. 返回值只有一个结果对象：`signal ∈ ok/quota/invalid/ip_limited/rate_limited/data_missing/not_entitled/server_error/network/client_error/unknown_upstream`，附规范化 `code` 与是否允许重试；状态变更、通知、台账只消费该对象。

## 3. 冷却 24h 契约裁定

**选择：改实现守契约，不批永久例外。** api-contract §7.1 DELETE 行与 T-T25 半开区间不变，T-A54 的 orphan 规则不变。

- 「上游无恢复截止」与「删除后的隐私保留期」是两个字段/两个概念：`paused_until=NULL` 只在 live 绑定上表示不自动恢复；一旦 detached，必须另有 `retention_deadline=deleted_at+24h`。
- 24h 后不得恢复指纹、冷却状态或旧 scope；新的同证提交按 pending verification。持久安全闩锁可保留为不可复原的匿名历史事实，但不再参与其他证书或新绑定的门禁。
- e8ffe05 的永久保留补丁明确否决，不得合入；0029 重写时把该约束放进 DB 默认值/触发器及定点测试，不能只靠应用记忆。

## 4. 工作量、复用与风险对比

| 方案 | 估算 | 测试复用 | 风险与结果 |
|---|---|---|---|
| **A 重写（选定）** | 后端 2.5 人日 + 测试/复核/运维 1.5 人日，排期 **4 个日历日** | 按场景约 **65–75%**：响应文法、24h 边界、权限/RLS、锁与通知大多保留；Redis 索引/ACK 回填场景删除，DB outbox 与崩溃矩阵重写 | 中。新迁移与切换有风险，但模型和故障面显著减少；当前未部署，回退只是不合入 |
| B 最后一轮修复 | 编码 1.5–2 人日 + 复核 0.5–1 人日 | 表面可复用 ≥90% | 高。需同时修四类 P1，并继续维护四事实源；无法证明下一交错不存在，不建议用实跑验证 |
| C 冻结至探针后回填决策 | 当前开发 0；产品至少推迟到探针与后续评估完成 | 不重写 | 最低实跑风险，但名单/live 继续不可用，根因留到更晚且探针后仍要重做 |

### 若强行选 B，剩余项必须一次完成（仅供对比，不是派单）

1. 恢复 24h `_remember/_take/purge`、0029 触发器、换证承接全部一致，并覆盖 null/有限/到期 × hold/DELETE/PUT。
2. 合并两个限流识别函数，覆盖 error 递归、chunk 边界、长空白/超限、103.0 与普通业务字段；所有未知体 fail closed。
3. ACK 前重新核对 v1/v2/UUID 组、源消息和 DB 预留，解决历史组漏认。
4. backfill、Lua、purge 全程同用户锁与 generation 围栏，补「扫描后/写前、写中、提交后清 Redis 前」崩溃矩阵。
5. 复跑 b–j 全部相关定点与独立 RV；任何新 P1 都不得实跑。

即使五项全绿，也只是再证明一组已知交错，不能消除下一组设计组合，因此不选 B。

## 5. A 的排期与验收门

- **D1**：DB 绑定/冷却/暂停 schema 与生命周期；24h 约束、outbox 表/复用决策、权限负例。
- **D2**：API 同事务 outbox、ingest 认领/generation 围栏、purge 协议；删 Redis 索引执行路径。
- **D3**：唯一响应判定模块及四调用方接线；文件闩锁/SQLite 退役；探针只换判定调用，不改时段、次数或台账。
- **D4**：定点故障矩阵、架构师 + GPT 独立复核、修复与运维合成环境切换演练；通过后才由 Chief 另派 1 次验证 + 3 次名单的实跑验收。

**完成门（缺一不可）**：

1. DB outbox 唯一执行来源；停掉 Redis 仍只执行一次；历史 Redis 消息不会自动执行。
2. 24h 等号、首次 DELETE 起算、有限截止、叠 hold、换证/同证重绑、逾期不复活全部通过。
3. 四类响应形态在 4093/4096/64 KiB/16 MiB 边界有正反例；未知超限 fail closed；四调用方无第二判定实现。
4. 注销与投递的六种交错均无复活、无旧 generation 状态覆盖；已发请求只计账、不回滚事实。
5. A 停不阻 B、orphan 不阻 B、公共 STOP 停全部；权限/RLS/密文/普通用户清闩负例全过。
6. 新迁移单 head、可升降、与角色授权同事务验收；相关定点测试、ruff/mypy、secret_scan 全 0、diff --check 过；无全量/coverage、无真实调用。
7. 架构师与 GPT 独立复核均无 B/P1；运维只先在合成环境演练，探针不被阻塞。

## 6. 影响

- 后端：按本裁定新分支实现；废弃 T-B99b–j，不做第十一轮补丁。
- 测试：保留有效场景表，重写 outbox/注销/崩溃矩阵；不得用旧「128 次定点全过」替代新架构验收。
- 运维：0029 尚未部署，按重写版单迁移准备；旧流只归档不自动重放；真实栈切换另派。
- 探针：T-B05/T-B86 照跑，共用判定模块时只做适配，暂停/回滚其执行版本须另报 Chief，不得因名单重写停摆。
- 契约：24h 不变，无新增外部字段；内部 outbox/generation/scope 不进 API。
