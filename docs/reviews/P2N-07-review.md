# P2N-07 后端评审

## 范围与结论
- 目标提交：`16f2a1a`、`9dd6047`；行号基准：`f811992971e83837de7905eb3f783e7f4f922e99`（评审时 HEAD）。
- 两提交仅存在于盒子本地分支，远程包含查询为空；本次不克隆、不推送，只读现有本地工作副本。
- **结论：不通过完整 P2N-07 验收；阻断 2、重要 3、建议 1。** 手工计划/版本和草案确认事务有基础，但草案生成及生产条件执行链未闭环。
- 依据：契约 §7.7、§7.7B T-A29、§7.11；plan §2.5.8、§2.5.9。以下均由后端修改；前端无需绕过错误或拼装业务结果，我无需补契约。
- HEAD 已有后续 P2N-06 通知接线；只将它作为现状核对，不将其新增代码误归入目标两提交。

## 阻断
### B1 草案生成永远失败，正常用户无法进入确认链（后端）
- 位置：`src/backend/app/plans/drafts.py:102–112`。
- 通过全部候选校验后仍无条件抛 `503 UPSTREAM_UNAVAILABLE`；没有创建草案，也没有用户触发的 `open/released → drafted` 事件。确认测试只能人工种草案，不能证明真实闭环。
- 契约 §7.7 POST /plan-drafts 应返回 `201 PlanDraft`，plan §2.5.8 要求数量/价格区间、费用、上下文与人工清单均可生成。
- 修复：用已有可信缓存和版本化规则完成预算/滑点/费用/清单适配，在一个事务保存不可变草案、快照与信号状态事件；真实缺口保留失败，但不能所有合法请求固定失败。禁止伪造缺失输入或调用未经批准的上游。
- 验收：本人可解释 open/released 信号经真实 HTTP 生成草案再确认；重生成保留旧草案，错误优先级沿 §7.7 七步。

### B2 生产价格条件没有可运行数据链，条件任务也没有自动调度（后端）
- 位置：`src/backend/app/plans/worker.py:118–169`、`:289–300`；`src/backend/app/workers/jobs.py:365–366`、`:410–419`、`:451–488`。
- 非 test 环境在读取快照后必定以 `production_quote_adapter_missing` 跳过；test 环境只接受 synthetic。TASKS 仅注册处理器，schedule/slot_jobs 未排此任务，全仓调用检索只见定义/注册/自检手工入队；生产不自动检查，日期也不会到点运行。
- 契约 §7.7B/§7.11 要求当前条件满足后触发提醒。安全拒绝无可信数据正确，但这是交付缺口，不是已完成功能。
- 修复：接入本人授权、unadjusted 最新行情/昨收，按配置 `effective_stale_threshold_s` 检查真实 data_as_of（不能只相信输入 fresh/expires_at），保留停牌/缺价 unknown+gap；接入获批用户自动入队与日期恢复检查。worker 继续使用 aia_api，不能改用属主规避权限。
- 验收：生产模式可信本地缓存可触发；复权/超时/停牌/他人快照不触发；停机期间价格不回看，恢复仅按当前新鲜价判定；不做麦蕊实调。

## 重要
### I1 价格等号错误地不触发（后端）
- 位置：`src/backend/app/plans/worker.py:175–176`；错误预期见 `src/backend/selfchecks/test_p2n07_plans.py:555–558`。
- 实现为严格 `>`/`<`，与 T-A29 的 `≥`/`≤` 相反；last=threshold 会漏报。
- 修复：使用包含等号的比较；同步改掉把 price_above 10.00 对 10.00 断言为 false 的测试，补 price_below 等号、上下邻值与重复检查只生成一次的用例。

### I2 pct_change 被整体跳过，且 pct=0 可写入（后端）
- 位置：`src/backend/app/plans/worker.py:101–103`；`src/backend/app/plans/models.py:52–60`；错误预期见 `src/backend/selfchecks/test_p2n07_plans.py:666–697`。
- worker 将已有明确裁定的涨跌幅方向标记 undefined；模型只检查格式/量级而未拒绝零（含 -0.0000）。
- 修复：写入 pct=0 返回 `400 VALIDATION_ERROR` / issue=invalid；以不复权 last/prev_close 做 Decimal 运算，ROUND_HALF_UP 四位后按正数 ≥、负数 ≤ 比较；缺昨收只 unknown+gap prev_close。测试覆盖正负等号、四位舍入边界、缺昨收及零拒绝，不能保留 undefined 为正确结果。

### I3 日期没有写入下界、09:00 边界、顺延与补发（后端）
- 位置：`src/backend/app/plans/models.py:61–65`；`src/backend/app/plans/service.py:75–91`；`src/backend/app/plans/worker.py:39–60`、`:104–110`、`:186–198`。
- 仅验证 ISO 日期，过去日期也能保存；只判断当前日等于 on，交易日 09:00 前也可触发，非交易日目标不会顺延，目标日后直接记 date_catch_up_undefined，evidence 无 scheduled_for。
- 修复：创建/新版本按北京时间写入当日拒绝 on<today（400 invalid）；用有覆盖的交易日历求 on 当天或其后首个交易日 09:00，当前时刻达到后触发；恢复时补一次，triggered_at 为实际时刻，evidence 带原定 scheduled_for。不得用“当前日必须开市”的总前置条件挡掉已到期日期的恢复处理；缺日历仍 unknown+gap。
- 验收：today 前/等于 today、08:59/09:00、周末顺延、跨日停机恢复、缺日历与重复检查。

## 建议
### S1 给 9dd6047 补事务中途失败与并发确认回归（后端）
- 位置：`src/backend/selfchecks/test_p2n07_plans.py:390–448`、`:538–552`；事务代码 `src/backend/app/plans/drafts.py:336–378`。
- 当前确认用例覆盖成功后顺序重放与唯一 confirmed 事件，并发用例覆盖手工计划/版本；尚未证明多信号确认中途失败及并发确认场景。静态事务结构未发现确定的半提交缺陷，不作为阻断。
- 建议：第二条 signal_transition 或最终审计写入时注入失败，断言计划/版本/确认记录/草案头/全部信号及事件一起回滚；同体并发返回同 plan，异体并发仅一个成功、另一个 409 IDEMPOTENCY_CONFLICT，不重复事件。

## 已核对、不新增问题
- 本人隔离：计划/版本先经 `service.owned:65–72`；草案 `drafts.own:115–120`；提醒 `api.own_alert:252–259`，他人资源与不存在均 404。生成草案的他人 signal_ids 按契约特例返回 400，不误判为隔离缺陷。
- 版本不可变：`service.version:124–164` 只插入版本/条件、移动头指针；基线迁移 APPEND_ONLY 包含两表并建立禁止 UPDATE/DELETE 触发器；qty/price/stops 放不可变 completeness，不要求新增重复列。
- 并发/幂等：owner advisory lock + 行锁串行化，base_version_no 检查、版本唯一约束与手工写 Idempotency-Key 已接入。条件按 condition id 去重并使用稳定 alert UUID，新版本新条件重新布防；当前条件一次触发的静态结构合理。
- 9dd6047：`drafts.confirm:187–225,336–378` 的计划、确认记录、草案头与候选 confirmed 事件均同一 engine.begin；先验证全部候选 drafted，再写，prior 分支先返回原计划，不重复迁移。未发现必须另开事务或需要补契约的问题。
- 0024：`src/backend/migrations/versions/0024_p2n07_plan_times.py:7–29` 顺接 0023，仅新增带时区状态时间列，无正文覆写或扩权。updated_at 默认迁移/插入时刻，不能解释为历史真实变更时间；升级存量语义需部署验收，未运行数据库迁移。
- DB 角色：`deploy/compose/docker-compose.yml:163–172` worker 用 aia_api；`deploy/db/roles/grants.sql:94–110,167–225` 的现有 DML/序列授权覆盖条件任务，0024 新列不含密文。只做静态核对，未声称完成实际 aia_api 权限回归。

## 验证与边界
- 定点 ruff：`uv run --no-project --with ruff ruff check app/plans app/db/tables/research.py migrations/versions/0024_p2n07_plan_times.py selfchecks/test_p2n07_plans.py`（src/backend 目录）通过。
- 未跑 pytest：`selfchecks/test_p2n07_plans.py:35–40,64–68` 依赖专用 PostgreSQL/Redis；按本任务仅在无需外部服务时运行的限制跳过。未跑全量测试/coverage，未使用真实用户样本、上游调用或任何密钥。
- 交付前仅对本评审文档运行指定 files 模式 secret_scan（阻断须 0）及 `git diff --check -- docs`；本地 pathspec 提交，不 push，不接触其他人的暂存/WIP。

DeepSeek：未用，原因 评审结论禁止外包。
申请新任务：后端修复 B1/B2 与 I1–I3 后定点复审；并核验真实草案生成至确认最小闭环。
