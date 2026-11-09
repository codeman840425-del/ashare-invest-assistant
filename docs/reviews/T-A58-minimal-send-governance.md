# T-A58 最小方案（初稿）：麦蕊发送治理只保四件事（架构师，北京 2026-11-10）

> 状态：**初稿，待用户确认后才实现**（用户 2026-11-09 指令：停 T-B101 重写，只保单出口发送锁、公共 STOP、128 次计数台账、每日名单 3 次上限，优先复用已验证路径）。基线 team-b=98d36ec。
> DeepSeek：未用，原因：架构裁定不外包。

## 0. 判定

T-A55/T-A57/T-B101 的 DB outbox、Redis 唤醒、HPKE 全家桶是**为多用户多证书规模设计的**；本项目是单人系统（1 张证书、单出口），四件事实各自的文件实现已被 T-B05 第 2–4 段实跑验证（61+6 次真实外呼 0 次 103/429、STOP/租约/台账行为符合预期）。**最小方案 = 直接采纳探针路径为产品路径，不再引入第二事实源。** 判定依据：团队 memory「团队按交接文档分 7 角色」、plan §2.1B T-A53 名单链 3 次、探针代码与实测报告（docs/handover/team/reports/T-B05-20261109.md、T-B05-segment3.md）。

| 四件事 | 现成机制（实跑验证出处） | 采纳的属性 |
|---|---|---|
| 单出口发送锁 | `app/ingest/send_control.py::critical`（flock 独占 inode，T-B99 合成 32 项 + T-B05 实跑） | 一进程一把、崩溃自动释放、无 TTL 竞态 |
| 公共 STOP | `shared_gate.py::stop_present/write_stop`（T-B05 第 3 段实跑 0 触发但路径就绪） | 全局停机、仅授权人工删、fail closed |
| 128 次计数台账 | `probes/tb86_offline.py`（flock + O_NOFOLLOW 0600 + fsync 落账后才放行 dispatch，T-O46 接线 0/128） | 发送前落账、失败也计数、总数 128 硬顶 |
| 每日名单 3 次 | T-A53 R2/R4（18:00–23:59:59、60 秒间隔、无重试，名单账本独立） | 第 4 次建连前拒绝、不跨日补打 |

## 1. 单一事实源

**文件目录是唯一事实源**（运维挂载的一个私有 POSIX 目录，非 DB 非 Redis）：`STOP`（全局停机）、`state-*.json`（逐源分钟账）、`mairui-batch-*.count`（批次台账）。理由：单人系统无多写者，文件路径已被实跑验证；再叠 DB/Redis 事实源正是用户否决的过度设计。DB 只保留**业务行**（`user_data_licence_status` 展示状态），不参与门禁判定。

## 2. 四件事逐项

### F1 单出口发送锁

- 复用 `send_control.critical()`：所有外呼（名单、日 K、探针、验证）在 dispatch 前必须持有；同线程重入拒绝（`shared_control_reentry_refused` 已实现）。
- 探针优先语义照 T-A53 R2.3：探针持锁或存在在途不确定时产品不发起；反方向同理。

### F2 公共 STOP

- 复用 `stop_present/write_stop`。STOP 存在 → 拒绝一切外呼（`GateClosedError("shared_STOP")`）；人工删除前须确认两侧已停、距最后请求 ≥60 秒、出口唯一（run_all.py 头部注释既有规则）。

### F3 128 次计数台账

- 复用 `tb86_offline` 台账模式：flock 持锁贯穿 dispatch；**发送前** append 记录 + fsync；失败/超时/STOP 都计数不回滚；`total ≥ 128` 或分段接口上限 → 建连前拒绝；台账状态未知 → fail closed（`counter_state_unknown`）。
- 台账按批次独立（T-B05 共享预算与 T-B86 的 128 是两本账，T-O46 已接线），不新建替代台账（T-A53 §0：不挪用、不重置）。

### F4 每日名单 3 次上限

- T-A53 R2/R4 语义不变：交易日 18:00–23:59:59、三端点固定顺序、每端点 1 次、间隔 ≥60 秒、无重试、不跨日补打；名单账本独立（建议 `mairui-daily/v1` 键），第 4 次建连前拒绝；3 次不含日 K（日 K 走 P1 队列另账、须当次授权）。

## 3. 明确删除项（与 T-B101 重写的差异）

| 删除 | 理由 |
|---|---|
| DB outbox（`ops.mairui_verification_outbox`） | 单人无多消费者；验证按「PUT → ingest 轻量接口 → 状态回写」既有路径 |
| Redis 唤醒/ACK/回填 | 无并发消费者；SSE 状态推送照旧 |
| HPKE 绑定/scope/generation 三生命周期 | 1 张证书无跨证书恢复问题；DB 状态行照旧展示 |
| PG 会话锁跨临界区 | flock 单锁已覆盖；DB 锁留作业务事务一致性，不参与门禁 |

保留（非四件事但被依赖）：证书只经环境变量注入探针进程、脱敏断言（写盘前拒绝含证书）、出口 IP 自检。

## 4. 改动面与工时

| 项 | 内容 | 预计 |
|---|---|---|
| 后端 | 名单链与日 K 接 `send_control.critical` + STOP 检查 + 名单账本（探针三模块已在 T-B99e worktree，cherry-pick 后接产品调用点） | 0.5–1 人日 |
| 测试 | 四件事负例（STOP 拒发、第 4 次拒发、台账 fail closed、重入拒绝）+ 既有 128/名单定点不回退 | 0.5 人日 |
| 运维 | 挂载点/权限照 T-O44 既有布线，无新增 | 0（沿用） |
| 架构 | 本裁定 + plan/契约同步 | 本单 |

切换顺序：**先旁路后切换**——产品侧新代码先以「只读门禁（只检查不阻断）」上线一个交易日，日志确认与探针行为一致后，才改为强制阻断。0029 领先问题照 T-A57 §7（清空两私有表后 0030 拒迁断言保留）由运维另走 runbook，不在本单。

### 旁路模式精确定义（T-A59，北京 2026-11-10）

「旁路」针对的判定与顺序完全同强制模式，唯一差别是命中后的动作：

| 判定（同序同语义） | 强制模式动作 | 旁路模式动作 |
|---|---|---|
| F1 发送锁不可得（探针持锁/在途不确定） | 放弃本次外呼，记 `skipped_lock` | **照常发送**，记 `bypass_lock_would_block` |
| F2 STOP 存在 | 建连前拒绝（0 HTTP） | **照常发送**，记 `bypass_stop_would_block` |
| F3 台账 ≥128/分段上限/状态未知 fail-closed | 建连前拒绝 | **照常发送**，记 `bypass_budget_would_block` |
| F4 名单第 4 次/窗口外/间隔不足 | 建连前拒绝 | **照常发送**，记 `bypass_daily_would_block` |

- 旁路日志每条命中记录：`{code, would_block, ts, snapshot}`，`snapshot` 含该判定当时的台账总数、名单当日计数、STOP 路径存在性、锁持有者标识——与探针侧同判定逐条可对齐（T-T34 验收「观察日志正确性」即此对齐）。
- **不旁路的部分**：台账落账本身照常（fsync 先于 dispatch、失败也计数）；证书脱敏断言、出口自检、探针自身门禁全部照常。旁路只作用于「拒绝外呼」这一动作，绝不放松落账与脱敏。
- 开关：单一配置键（如 `send_governance.enforce: true|false`），默认 `false`（旁路）。切强制 = 改配置 + 重启，不改代码；切换须 Chief 携旁路期观察结果与 hash 报用户确认后另行派单。
- 观察期 = 1 个交易日（名单窗口 + 至少一段探针时段重叠）。旁路期内若发生真实 103/429，探针侧既有 STOP/即停规则照常生效（旁路不掩盖真实停机——那是探针侧自己的门禁，不属本产品开关管辖）。

## 5. 验收（可转定点测试）

1. STOP 存在时名单/日 K/探针全部建连前拒绝（0 HTTP）。
2. 名单第 4 次请求建连前拒绝；台账当日计数 = 3（失败也计数）。
3. 台账文件权限非 0600/链接数 >1/状态未知 → 拒发（fail closed）。
4. 同线程 dispatch 内再取锁 → 拒绝。
5. 旁路期日志与探针台账逐条对齐；切换后强制阻断生效。

## 6. T-A60 返修口径（五条，北京 2026-11-10；对象 tb-T-B102 = aedab8e + c1c8877 + eaa4744）

RV-15 六项 P1 中四项需定口径，逐条裁定（已核 tb-T-B102 实码与探针既有门禁；五条全部为「复用已验证路径」边界内的返修，零新设计）：

### R1｜锁互通：判定统一、锁文件唯一（对应 RV-15 ①③）

- **根因**：探针 `SharedGate.acquire()` 用 O_EXCL lease 文件（`single-egress.lease.json`）+ `probe-waiting.lease.json` 优先占位互斥；产品 tb-T-B102 用 `send_control.critical`（flock `send-control.lock`）。两套机制物理互不相干——这是①悬挂软链、③锁互通风险的共同源头。
- **裁定**：两侧统一走 `send_control.critical`（同一 `send-control.lock` flock，T-B99e 本为两侧共用而写）。lease 文件降级为「存在即 busy」的**旁路观测信号**，不再作互斥依据；软链/悬挂/权限判定沿 `send_control` 既有检查（nlink=1、非符号链、0600、属主一致）。
- **顺序（编排者定）**：产品侧半边（wire 判定/软链判定统一到 send_control 入口）在 T-B102b 本轮做；**探针 common.py 切锁留到明天全部麦蕊触点跑完后的空窗**（15:45 F21 收盘后～后天之间），单独小单 T-B103 执行。空窗前探针零改动照跑。
- 过渡期语义：T-B102b 上线～T-B103 完成之间，产品侧除 flock 外仍观测 lease 文件存在性（`legacy_lease_present` 已有），探针持 lease 时产品按 R1 判 busy——互斥仍成立（探针写 lease、产品认 lease），只是反向（产品持 flock、探针不认）在空窗后由 T-B103 补齐。空窗期内产品与探针时段本就错峰（T-A53 R2），实际并发风险为零。

### R2｜证书闩锁互认：halt 文件存在即停（对应 RV-15 ②）

- 产品 `sync_halts`（live.py）读 `*.halt.json` 反馈通知那半**不动**；缺的是发送判定时不看探针 halt。
- **裁定**：`Governance.stops` 增一类：`root/*.halt.json` 任一存在且 `code∈{103,429}` → 视同 STOP（旁路记 `bypass_stop_would_block`，reason=`probe_halt_present`）。**不解析 licence_id**——单人系统一张证书，按 T-A53 R3「任一侧触发→两侧全停」原语义。产品自身 103/429 已写 STOP（`_write_stop_unlocked`），闭环。
- halt 文件本身的软链/悬挂判定同 `stop_present` 语义：不可判定即视为停（fail closed）。

### R3｜分钟账与产品间隔回装（对应 RV-15 ④）

- tb-T-B102 的新名单账 `daily_lists.count` 只管 F4 三次/日，把旧 `SharedGate.reserve/product_delay` 的分钟账（T-B05 实跑验证）丢了——确认这是缺陷不是精简。
- **裁定**：产品发送前读 `state_path`（`requests.json`）分钟账：`inflight=true` → 拒（uncertain）；60s 滚动窗口内调用数 ≥ limit → 拒；产品侧 `last_finished` 距今 <60s → 拒。探针写账照旧（已实跑）。`expected_egress` 读 `policy.json` 不动。旁路期命中记 `bypass_lock_would_block`（uncertain/分钟满）与 `bypass_daily_would_block`（间隔），与 F1/F4 归口一致。

### R4｜锁忙语义：恢复 tick 重试（对应 RV-15 ⑤⑥）

- tb-T-B102 删了 `return "busy"`，锁忙落进 `except Exception → batch failed` 且 ACK 消息——错误。
- **裁定**：flock `LOCK_EX|LOCK_NB` 得 `BlockingIOError` → `dispatch` 抛 `GateClosedError("shared_control_busy")` → `process()` 捕获后**直接 `return "busy"`**：不写 batch failed、不标 attempted、不 ACK；tick 层 `result=="busy" → continue`（消息留流内下一 tick 重试）。仅确定性拒绝（授权失效/deadline/STOP 落账后/预算尽）才标 failed。旁路模式下同样 return "busy"——锁忙是能力缺失不是治理判定，不属旁路范围。

### R5｜观察口径：ledger128 对齐列（对应 RV-15 P2⑦）

- `snapshot` 增 `ledger128_total`（128 台账当前总数，**只读**），与 `ledger_total`（名单账）并列；旁路与强制两模式都记。不动 128 台账本体。观察期即可逐条对齐两本账（T-T34/T-O48 验收口径）。

### 返修顺序与单据（编排者 T-A60 验收定）

- **T-B102b（后端，本轮）**：R2/R3/R4/R5 全部 + R1 产品侧半边。全在产品代码内，探针零改动。
- **T-B103（后端，空窗单）**：R1 探针半边——common.py 的 `SharedGate` 互斥切到 `send_control.critical`，lease 降旁路观测。时机=明天 15:45 F21 收盘后全部触点完成～后天之间，单独派单。
- RV-15 复验对象=T-B102b 全量 diff：四件事边界零突破 + 五条口径逐条核。

## 7. T-A61 过渡期协议两口径（北京 2026-11-10；对象 tb-T-B102c = 7dea63f）

### R6｜分钟账并发写入：禁止回滚覆盖，改为「读侧合并 + 追加免回退 + 空白覆盖白名单」

RV-15c 抓的竞态属实：产品「读旧快照 → 预留写入 →（锁忙）cancel_unsent 回写 original」会覆盖探针在产品读快照之后、回滚之前写入的预留——探针随后发送而分钟账上无此记录。过渡期两套写者并存（探针 SharedGate 写、产品 MinuteLedger 写），任何「恢复旧值」式回滚都 unsafe。裁定（全部在已验证路径边界内，无新协议）：

1. **读侧合并已有且正确**：`MinuteLedger.read()` 合并 `state-*.requests.json` 与 UUID `*.requests.json` 全部来源的 calls/inflight/last_finished——保留。这是过渡期正确性的第一道闸：判定永远看全部账。
2. **回滚改为「减去自己那条」**：`cancel_unsent()` **禁止回写 `self.original` 整快照**。改为重读当前文件 → 删除**仅属于本次预留的那一条时间戳**（`pending["calls"][-1]`，按值匹配、恰一条；找不到＝他人已覆盖，放弃删除直接保留——多记一条只是保守，漏记才是危险）→ 回写其余不动。`complete()` 同理：基于重读后的当前态 + 自己那条的 finished 标记回写，不基于 pending 快照整体覆盖。
3. **追加免回退**：任何写者（产品或探针）之后，`calls` 数组只增不减（60s 窗口滚动剔除除外——那是时间推进不是回退）。`last_finished` 单调不减。
4. **过渡期时限**：本协议只活到 T-B103 切锁完成。切锁后单一写者（flock 持有者），read-modify-write 在锁内天然串行，cancel 可恢复精确快照——**T-B103 交付时须一并收窄回滚语义**并在其验收里覆盖。
5. **负例（RV-15c/T-T34 增补）**：①产品读快照后注入探针预留 → 产品 busy 回滚 → 断言探针那条仍在文件里；②探针预留后产品 complete → 断言两者 calls 都在；③cancel 时文件已被他人改写（找不到自己那条）→ 保留现状不报错、不覆盖。

### R7｜跨日续发：硬截止，当日作废重派（窗口判定不旁路）

确认编排者建议方向，三条：

1. **窗口判定不旁路**：`outside_daily_window`（18:00–23:59:59、交易日、`now.date()==expected_day`）是**窗口合法性判定**不是治理命中——旁路模式照常拒绝（旁路只放宽 F1–F4 的治理阻断，不改变「这单本来就属于昨天」的事实）。tb-T-B102c 现实现里窗口判定走 `_decision("daily", ...)` 会被旁路放行——**改为窗口不符直接 `GateClosedError("daily_window_expired")`，两模式一致**。
2. **跨日批次作废重派**：部分成功批次持续锁忙保持 `requested` 跨过 23:59:59 → 下次处理时按 `daily_window_expired` 标 `failed`（error_code 同名，区别于授权失效），**已完成的端点结果保留入库**（持久化逐端点成果是 T-B102c R3 已做的），不重发；新交易日走全新批次（outbox/beat 重新派）。回执若跨日：`read_grant` 的 `not_before/expires_at` 边界照旧判失效，不因跨日续期。
3. **deadline 扫描**：tick/处理入口先判 `clock() >= deadline_at`（已有）与窗口（本条新增），两者任一触发即作废，不进入 dispatch。旁路期同样作废——不存在「旁路模式把昨天的单发出去」。

### 落点

- T-B102c 返修单（RV-15c 后续）按 R6/R7 执行；T-T34 负例按 R6.5/R7 各增补；T-B103 验收含 R6.4 收窄。
