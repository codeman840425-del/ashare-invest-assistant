# T-A10 前端同步契约 v0.2.9（提交 2/3）

- 提交：`7a3e9cb` feat(frontend): 同步契约 v0.2.9（T-A10）；父提交 `c9e1e73`（他人 T-B47，09:05 北京时间）。只在本地，**未 push**。
- 提交时间：2026-11-02 09:09（北京时间），截图脚本与横幅修正为同一提交的 amend（本地未推送）。
- 范围：28 个文件，全部在 `src/frontend/`（`git diff --cached --stat` 已核对，non-fe staged 为空）。
- 依据：`docs/api-contract.md` v0.2.9 变更表 #1–#14、#26（HEAD 687159f 起的文本）；清单 `reports/T-A10-pending.md`。
- 顺序：按 8:41 的调整，评审修复已先单独提交为 `d0c7ccb`（见 `review-b23401a-fixes-frontend.md`），v0.2.9 改动当时用 `git stash` 隔开，修复提交后再恢复。

## 编排者点名项

| 项 | 做法 | 测试 |
|---|---|---|
| CONTRACT_VERSION → v0.2.9 | `api/enums.ts`；新增 4 个枚举键（`candidate_signal_event_cause` 6 值，研究候选 3 个）；示例数据横幅改为读 `CONTRACT_VERSION`（原先写死“v0.2.8”） | t-a10「版本与枚举」、横幅断言；t-a09/t-f22 版本断言改 v0.2.9 |
| mock pnl 改 null | 可转债行 `market_value/pnl/pnl_pct = null`、`estimated: true`、`security_type: null`，`weight_pct` 按成本；顶层 `data_status: partial` | t-a10 #1–#3 |
| 去掉 plan_confirmed | 事件 cause 只用 6 个取值；drafted→confirmed、忽略用 `user` | t-a10 #6、t-f17 causeText |
| events 分页 | `GET /candidate-signals/{id}/events` → `{items,next_cursor}`，`at desc, id desc`，不返回 `detail`；详情页用 `useCursorPages` + `<CursorPager>` | t-a10 #6（API + “加载更多”UI） |
| 估算标记读 `estimated` | 持仓页、终端 WatchTable 改读 `estimated`；“可转债·无行情”文字仅在 `security_type===null` 时附加代码前缀判断做文案区分，是否估算不再看前缀 | t-a10：股票行 estimated=true 显示无行情且不写“可转债”，113 开头行 estimated=false 不标 |
| 证券代码/名称用原因对象字段 | `NonExecutableReason.security_code/name`；已解除原因列表直接用，去掉按 signal_id 逐个取信号 | t-a10 #8 |
| status=all | 默认 active；信号详情“自动重评状态”、建议详情策略卡片（显示“已解除”标签）传 `status=all`；mock 校验 status 取值，非法 400 | t-a10 #12（3 项） |
| 放弃草案去备注框 | 弹窗只留说明；`discard.mutate(undefined)` 发 `{}`；mock 忽略 `note` 不报 400 | t-f18 放弃（请求体捕获为 `{}`、无 discard-note）、t-a10 #11 |

## 其余 v0.2.9 项（T-A10-pending P 编号）

| P | 契约 # | 前端结果 |
|---|---|---|
| P01 | #1、#3 | 同上；`TerminalRow.holding.pnl/pnl_pct` 类型改可空，显示“—” |
| P02 | #2 | `positions[]` 与 `holding` 加 `security_type \| null`、`estimated` |
| P03 | #4 | 契约“前端改动：无”。ETF 成交量仍按“手”显示，未改 |
| P07 | #6 | 见上 |
| P08 | #7 | 列表不再自己推断冲突：对已加载信号按 ≤100 个一批查 `/non-executable-reasons?signal_ids=…&code=STRATEGY_CONFLICT`，有生效的该原因即标“方向冲突” |
| P09 | #8 | 见上 |
| P10 | #9 | mock：`BLOCKLISTED`/`USER_MUTED` 调 release → `409 REASON_NOT_MANUALLY_RELEASABLE`（即使示例数据 <host> 写错）；页面本来就不显示手动解除、引导到名单页 |
| P11 | #10 | 信号详情只请求 `scope=mine`（默认）；mock 支持 `mine\|site`，其他值 `400 {field:"scope"}`。全站统计在策略页展示，本次未做（策略页不在本任务点名范围） |
| P12 | #13 | mock：不同证券/方向/t_leg → `400 {field:"signal_ids"}`；方向相反且有 `STRATEGY_CONFLICT` → `409 SIGNAL_NOT_EXECUTABLE{reason_ids}` |
| P13 | #14 | mock 示例规则：科创板起买 200、递增 1，其他 100/100；确认时不满足 → `400 lot_rule{min_buy,step}`，`deviation_ack` 不能绕过；卖出只校验 ≤ 可卖数量。草案页输入不符合递增单位时提示“买入数量须按 N 股递增”；服务端 400 lot_rule 时按 details 显示“不少于 N 股、按 M 股递增” |
| P15 | #11 | 见上 |
| P17 | #15 | 契约写明 `/plans/{id}` 待 `/plans` 完整结构（问题 59），占位页不变 |
| — | #26① | mock：未被暂停时 resume → 204，不写审计（`licenceStore.adminResume` 只在状态变化时记日志） |
| — | #26② | 已是 created_at desc；无服务端筛选（问题 72），列表筛选提示“只筛选已加载的行”保留 |

其他：mock 事件时间不早于信号创建时间（示例数据里有 valid_until / detected_at 早于 created_at 的信号，导致创建事件不是最后一条；已在 mock 里收拢）。

## 测试结果

| 环境 | typecheck | eslint | vitest | 其他 |
|---|---|---|---|---|
| 带 .git 的工作区 | 通过 | 0 警告 | 33 文件 486/486 | — |
| 干净检出（`git worktree` <at> 7a3e9cb，`pnpm install --frozen-lockfile`） | 通过 | 0 警告 | 33 文件 486/486 | ignored-sources 错误 0 / 告警 4；`pnpm audit` 1 moderate（无 high）；build + check:dist 0 命中、dist-mock 反向自检有效；rc=0 |

- 全局测试超时保持默认（N8 已在提交 1 还原），新测试文件同样用 `beforeAll(() => preloadRoutes(routes), 30_000)`。
- 新增 `src/pages/t-a10.test.tsx` 19 项。

## 扫描（提交前，暂存内容）

- secret_scan files（204 个文件版本）阻断 0 / 警告 0；secret_scan staged 阻断 0 / 警告 0
- gitleaks dir（仓库配置 / 默认配置）no leaks；gitleaks git --staged no leaks
- 禁用词与 11 位数字（暂存新增行）0 命中
- 扫描前已 `rm -rf dist dist-mock`

## 截图（1440×900 深色，示例数据，控制台错误 0，外部请求 0）

`/workspace/team/reports/T-A10-frontend/`（脚本 `src/frontend/scripts/screenshot-t-a10.mjs`，结果 `result.json`）：
- `01-portfolio-estimated.png` 持仓：estimated 行“—”与“估算”，部分缺失状态
- `02-signal-detail.png` 信号详情：已解除原因（status=all）、状态历史分页与 cause 文案
- `04-discard-no-note.png` 放弃草案弹窗无备注框
- （03 建议详情未生成：示例中带已解除原因的信号没有关联建议，脚本按条件跳过；该显示由测试覆盖）

## 待定（契约未写清，未猜，mock 里的取法均已注释）

1. 事件 cause：创建事件（from=null）用哪个 cause 未写；→drafted（拟定草案）用哪个 cause 未写（#6 只写了 drafted→confirmed 与忽略用 `user`）。mock 分别用 `executability_check`、`user`。
2. `STRATEGY_CONFLICT` 的 evidence 里“对方信号 id”放在哪个字段（#7 只说写明）。前端冲突区仍按同证券信号列出，不依赖该字段。
3. 无板块的可转债在 `exposure` 里如何归类（#1 只说计入成本估算值）。
4. `PlanDraft` 没有 `instance_id` 字段，#13 却写“来自多个实例时 instance_id 为 null”——需明确是草案字段还是计划字段。
5. lot_rule 的 `min_buy`、`step` 放 details 顶层（#14 写法）还是 `details.fields[]` 元素（§4 VALIDATION_ERROR 通用写法）。前端两处都读，mock 用 fields[]。
6. POST /plan-drafts 方向相反时，400（同向校验）与 409（STRATEGY_CONFLICT）谁先判。mock 先判 409。
7. 科创板卖出零股规则标注【以交易所规则为准，研究员核对】；mock 卖出只校验 ≤ 可卖数量。
8. `GET /admin/audit-logs` 结构未定义（问题 73），#26③ 的理由与操作人前端暂无处展示。
9. #26⑤ 暂停/恢复通知：前端“无”，mock 未模拟该通知。

## 他人改动（未触碰、未 add）

- 他人新提交：`c9e1e73` T-B47（09:05 北京时间，在 d0c7ccb 之后、本提交之前）；之前的 `bbf58a0`、`483fe2c`、`439746e`。
- 工作区未提交（他人）：`src/backend/app/api/v1/meta.py`、`api/v1/portfolio.py`、`db/tables/signals.py`、`schemas/enums.py` 等后端修改，以及 deploy/、docs/、.github/ 下的改动与未跟踪文件。

## 需要谁做什么

- **架构师**：裁定上面待定 1–7（尤其 4、5、6，影响后端实现和前端读取）。
- **后端（T-B27 等）**：events 分页与 6 值 cause、reasons 默认 active 与 `all`、`security_code/name`、release 409、`scope`、discard 忽略 note、多信号校验、lot_rule、resume 幂等——前端已按契约对接，后端接口落地后需联调。
- **编排者/评审**：评审 7a3e9cb；策略页“全站跟踪统计”（#10 site）未排期，需要的话另派任务。
- **测试**：可用 t-a10 测试作为契约用例参考。

## 收尾补记（2026-11-02 09:47 北京时间）

- 7a3e9cb 之后的他人提交：0f8129b、4532478、47c4b9c、07a4e2b、db486aa、a8e055b、07b8d74（T-B47-R10，09:32），都没有涉及 src/frontend。
- 前端后续提交：5c282da（T-F23）、0e31218（CSRF 双提交，契约 §1.3 并入 v0.2.9，见 csrf-frontend.md）。
- 第 4 行说的 amend 发生在 7a3e9cb 定稿之前，是本地整理时做的。7a3e9cb 之后的修复一律用新提交，没有再 amend。
