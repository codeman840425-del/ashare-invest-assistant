# A-12 裁定：data_as_of 可空性外延（F-11 带出的 4 项待裁）（架构师，2026-11-11）

> 范围：F-11（PR #70）「待架构师裁定」节列出的 4 项 data_as_of 可空性。裁定基准：契约 §1.1 DataStatusBlock 语义（`unavailable` = 从未取到）、§1 混合来源响应规则、T-A53 §7.3 第 4 条（四端点 data_as_of 全空 null）、`bars.pending` 的 `adjust_as_of=null` 先例、日报顶层「非 null 最早值、全空 null」先例。
> 原则一句话：**凡是「DataStatusBlock 的 data_as_of」（语义=本响应实际用到数据的时点），可空性与 data_status=unavailable 同源——从未取到即 null，没有「编一个时刻」的合法路径。凡是「事件/证据的时间戳」（Evidence.data_as_of、SSE 事件的 at），它记录的是事实发生时刻，必有值，不可空。**

## 逐项裁定

### 1. SecurityProfile.data_as_of → **可空（`string(datetime) | null`）**

- 依据：SecurityProfile 是混合来源响应（公开主数据 + 本人证书部分），§1.1 明写「证书部分从未取到时 data_status 只按证书部分判定为 unavailable/partial」。证书部分从未取到时，`data_as_of` 无可取值——公开主数据侧只有 `master_as_of`（date 型快照日），不是「实际用到的行情时点」，拿它顶替等于伪造 datetime。与 T-A53 四端点「全空 null」同一裁法。
- 注意分工不变：`master_as_of: string(date)` 维持必填（主数据快照日，公开侧恒有）；可空的只是尾部 DataStatusBlock 的 `data_as_of`。

### 2. SectorFlowsResponse.data_as_of → **可空（`string(datetime) | null`）**

- 盘后数据端点，本人证书从未取到资金流 → `data_status=unavailable`、`items=[]`、`data_as_of=null`。与 financials/fund-flows 空态同构，无独立不可空理由。

### 3. MarketOverview.data_as_of → **可空（`string(datetime) | null`）**

- 契约 §7.3 /market/overview 行原文已是 `indices[].t: string(datetime) | null` + `DataStatusBlock`；T-A53 裁定第 2/3 条进一步把 breadth/regime/turnover_total 置 null 的场景写死（「不用本人小样本冒充全市场」）。最小切片下 indices 各 `t` 可全 null，顶层 data_as_of「取实际使用行情时点最早值」在全空时按 T-A53 第 4 条就是 null。**本条其实是 T-A53 已定语义的直接推论**，此处置确认并落契约字面。

### 4. Evidence.data_as_of 与快照类、SSE quote 推送块 → **维持必填（不可空）**

- **Evidence.data_as_of**：结构定义 `{..., data_as_of: string(datetime), fetched_at: string(datetime), ...}`——它是**单条证据的数据时点**，一条 Evidence 存在即意味着它引用的数据曾被取到（否则不产生这条证据、走 gaps）。「无数据」的表达位置在响应级 DataStatusBlock/gaps，不在 Evidence 内部。维持必填。
- **CandidateSignal/SignalEvent 等快照类**：同逻辑——对象存在 = 生成时快照存在（`snapshot_id` 必填），其 data_as_of 是快照事实属性，必有值。维持。
- **SSE quote 推送块**：quote 事件推送的前提是「有 quote 变化」，无数据不推（不推是缺数据的表达，不是推 null）。维持必填；若未来出现「推送占位事件」需求另裁，本单不预开。

## F-11 的类型面收敛

PR #70 已按「T-A53 点名的四端点先行、其余不动」实施——正确。本裁定生效后：
- F-11 后续补改（或 F-12）：`SecurityProfile`/`SectorFlowsResponse`/`MarketOverviewResponse` 三处前端类型从 `Sourced` 改 `SliceSourced` 同款（data_as_of 可空）；`FactorsResponse` 随 T-A158（#60）落地时一并（factors 不在本 4 项内，其可空已在 #60 裁定）。
- 快照类与 Evidence **不改**——前端保持非空声明是契约正确的，不是待办。

## 契约同步（本 PR 内完成）

§5.1 三处字面更新：SecurityProfile 代码块 `data_as_of` 行注 `| null`；SectorFlowsResponse、MarketOverview 响应说明各加一句「从未取到时 data_as_of=null（A-12）」。Evidence 与 SSE 块不加注（维持现状即必填，本裁定文档为据）。

不兼容性：三处全是「必填→可空」的单向放宽，旧客户端不受影响；后端实现侧（公开主数据未挂证书的 ETF/指数 profile、sector-flows 首次未取）按 null 返回，无状态机变更。
