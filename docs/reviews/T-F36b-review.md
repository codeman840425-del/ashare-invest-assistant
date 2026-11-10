# T-F36b 评审（架构师 T-A146）

- 评审对象：fe/T-F36b = 1d6bbf7（基 a0db774）。我只用 git show 和 git diff 查看，没有碰前端的 worktree。
- 对照：docs/T-A145 = 2ddefa5 的 `intraday-bars.md` §3.7 和 `today-view.md` §10，以及 T-A145 列出的 F36b 7 个返工点。
- **结论：通过，无阻断项。** 另有 6 条建议，其中 1 条是必改项，随下一个前端单处理。

## 1. diff 统计（a0db774..1d6bbf7）

| 文件 | 类别 | 新增 | 删除 |
|---|---|---:|---:|
| src/frontend/src/api/types.ts | 源码 | 12 | 12 |
| src/frontend/src/pages/today/TodayPage.tsx | 源码 | 3 | 3 |
| src/frontend/src/pages/today/tView.tsx | 源码 | 45 | 12 |
| src/frontend/src/pages/today/tViewModel.ts | 源码 | 79 | 34 |
| src/frontend/src/mocks/handlers.ts | 示例数据 | 2 | 2 |
| src/frontend/src/mocks/todayFixtures.ts | 示例数据 | 15 | 7 |
| src/frontend/src/pages/t-f36.test.tsx | 测试 | 44 | 33 |
| src/frontend/src/pages/t-f36b.test.tsx（新） | 测试 | 165 | 0 |
| **合计** | 8 个文件 | **365** | **103** |

- 分类小计：源码 +139/−61，示例数据 +17/−9，测试 +209/−33。
- 表由 DeepSeek 根据 numstat 整理。我用 `git diff --numstat` 和 `--shortstat` 逐行复核，数字一致。

## 2. 7 个返工点

| # | 返工点 | 判定 | 依据（函数名或用例名） |
|---|---|---|---|
| 1 | dev_pct 改为百分数，去掉 ×100 | 完成 | `fmtDevPct`、`tViewHints`（阈值直接展示，不再乘 100）；`t-f36b dev_pct 按百分数显示` |
| 2 | 数值字段改为 string(decimal)，新增 gaps | 完成 | `TView`；`t-f36 默认 mock` |
| 3 | 删除静默截断，违反时显示「—」 | 完成（另有 1 条必改建议，见 S1） | `availableBase`；`t-f36b 可卖超底仓显示核对中`；`t-f36 可用底仓不超过昨日底仓` |
| 4 | 区分不适用与不可用，用三种 key 的文案 | 完成 | `notApplicableText`、`TViewCell`；`t-f36b 不适用三种 key`；`t-f36b 不适用 t_view.session 在非交易日为「今日休市。」` |
| 5 | stale 标「已过期」，pending 标「拉取中」 | 完成 | `TViewCell`、`fmtShanghaiHm`；`t-f36b stale 不提示且标已过期`；`t-f36b pending 显示拉取中` |
| 6 | 只在 fresh 时提示；partial 时只对齐全的那项提示 | 完成 | `tViewHints`；`t-f36b 量比为空显示原因`（partial 只出 1 条） |
| 7 | 量比为空时显示原因 | 完成 | `GapNote`；`t-f36b 量比为空显示原因` |

另外两条也已兑现：§3.7 ⑧（`withThousands` 原样显示，见 `t-f36b 均价原样显示不再舍入`）；today-view §10（复用 `DataStatusTag` 和 `GapNote`）。

## 3. 阻断项检查（只限四类）

1. **正常路径错拦或错放：无。**
   - 正常路径包括 fresh、partial、不适用、不可用、stale、pending，都有用例覆盖。
   - `gaps.length && ...` 这个三元表达式：`&&` 的优先级高于 `?:`，所以 gaps 为空时结果是 null，界面不会多出一个 0。
2. **契约承诺没兑现：无。**
   - T-A145 原文 §3.7 ⑤ 写的是「复用既有 `isNotApplicable`」，实现没有复用，这一点被第二意见指出。
   - 本单裁定 ① 改了契约：全站函数保持不变，t_view 在内部判定，后端保证不适用时 gaps 只有一项。改完后实现与契约一致，前端不用返工。
3. **靠放宽断言让测试变绿：无。**
   - 改动的旧断言都随 T-A145 的契约变化，不是为了让测试变绿：截断改为显示「—」；t_view 为 null 只留给非持仓行；阈值改为百分数；量比阈值文案改为原样显示的「2 倍」。
   - `t-f36 默认 mock` 新增的类型断言偏弱（S3），但它是新加的断言，不是把旧断言放宽了。
4. **在用户的 Windows 部署上必然失败：无。** 改动全在前端纯展示层，不涉及路径、进程或服务。时区用 `Intl` 显式指定 Asia/Shanghai，与机器时区无关。

## 4. 复杂化检查

- 改动规模与验收需要相称。
  - 没有新依赖、新配置或新文件，唯一的新文件是用例 t-f36b.test.tsx。
  - 新增的纯函数有 `isDec`、`withThousands`、`roundHalfUp`、`fmtDevPct`、`notApplicableText`、`fmtShanghaiHm`。原因是 §3.7 ②⑧ 要求按十进制字符串精确处理，而既有的 `fmtNum` 走浮点，满足不了。
  - `TodayPage` 里的 `focusColumns` 从常量改成函数，只为传入 nonTradingDay，是最小改动。
- 可以接受的重复：`roundHalfUp` 与 `TrackingStats` 里的十进制舍入逻辑重复。本单不要求抽公共函数，避免扩大范围（S5）。
- **Codex**：T-F36b 报告写明「Codex 未用」，所以不涉及档位和精简的检查。

## 5. 复跑（我自己的临时 worktree，纯单测）

- 先确认 package.json 和锁文件与 main 一致，常用的 dev、preview、vitest 端口都没人用；node_modules 用符号链接借用 main 的，跑完已删。
- `vitest run`（t-f36、t-f36b）在 TZ=America/Denver、UTC、Asia/Shanghai 下各跑一遍，都是 18/18 通过。
- 四个 tsconfig 的 `tsc --noEmit` 都是 0。
- 没有起服务，没有跑 e2e，也没有跑全量用例。

## 6. 建议（不阻断）

| # | 建议 | 负责 |
|---|---|---|
| S1（必改） | `availableBase` 用绝对值比较上界：base_qty 为负、sellable_qty 为正时会原样显示，没有识别出违反契约（第二意见指出，我已核实）。应把 base_qty 为负也算作违反，并补一条断言。base_qty 为负本身就违反后端约束，不在正常路径上，所以不阻断，随下一个前端单修。 | 前端 |
| S2 | stale 时隐藏了 `GapNote`，原因只能在 `DataStatusTag` 的悬浮提示里看到。证书不可用（data_licence_unavailable）时，「去设置数据证书」的链接也看不到。建议 stale 时也显示 `GapNote`，可以去掉重复的「数据已过期」标题。 | 前端 |
| S3 | `t-f36 默认 mock` 用 `typeof` 属于 string 或 object 来判断，太宽。建议改为「是 null，或者是符合十进制格式的字符串」（第二意见指出）。 | 前端 |
| S4 | 持仓行缺少 t_view（后端还没升级）的情况，`TViewCell` 按「不可用」处理，但这个分支现在没有用例覆盖了。建议补一条。 | 前端 |
| S5 | 十进制舍入逻辑与 `TrackingStats` 重复。等 T-F37 统一时间格式时再一起考虑抽公共函数。 | 前端 |
| S6 | t_view.session 不适用时，标签显示「不适用」，正文显示「开盘后显示。」，两者语气不太一致。可以保留，也可以改成只显示正文。 | 前端（可选） |

## 7. 前端三问的裁定

### ① isNotApplicable 是否改成「任一 gap 为 not_applicable 即算」：不改

- **裁定**：全站的 `isNotApplicable` 保持「全部 gap 为 not_applicable」。t_view 继续用 `notApplicableText` 在内部判定「任一」，T-F36b 现在就是这么做的。
- 契约同步修改了两处：§3.7 ⑤ 写明不适用时 gaps 只有这一项，后端要在 `test_t_view_not_applicable_keys` 里断言 gaps 长度为 1；同时删去「复用 isNotApplicable」这句话。这样两种判定在 t_view 上结果相同。
- **依据**：api-contract §1.1 允许 gaps 混合多种原因（示例里 fresh 也带着 no_source）。如果改成「任一」，混合块会被整体标成「不适用」，而且 `GapNote` 的不适用分支只显示 `gaps[0].message`，真实缺数的原因会被盖住。这属于正常路径错放。
- **旧调用点**（rg 列出，逐个判断，均按函数或组件写）：

| 调用点 | 方式 | 如果改成「任一」 |
|---|---|---|
| components/common `DataStatusTag` | 直接调用 | 是传导点，影响见下面各页 |
| components/common `GapNote` | 直接调用 | 是传导点；不适用分支只显示第一条 message，会吞掉其他原因 |
| pages/stock/StockTabs 财务、资金流、因子、公告四个页签的空态判断 | 直接调用 | ETF 只有 not_applicable，结果不变；指数是 no_source，不变 |
| SuggestionDetailPage、DailyReportPage 的行状态 | 间接（传 gaps） | **受影响**：ETF 建议或日报行可能同时有 not_applicable（财务）和 no_source（新闻），会被整体误标为不适用 |
| research/VersionView、signals/CandidateSignalDetailPage | 间接 | **可能受影响**：证据块同样可能混合 |
| market/MarketPage（两处）、stock/StockPage（行情、档案）、stock/PriceChartPanel、terminal/ChartPanel、portfolio/PortfolioPage | 间接 | 目前不产生 not_applicable，结果不变 |
| pages/today/tView `TViewCell` | 间接，只传不适用的 gap | 结果不变 |
| TrackingStats、DailyDimensions、WatchTable、RiskControlsPage、DailyReportPage 汇总、TodayPage 两处 | 不传 gaps | 不受影响 |

### ② fmtTime 遇到 Z 结尾的时间：另开低优先级单 T-F37（前端），不阻断 F36b

- **依据**：
  - api-contract §1 写明「服务端统一输出 +08:00」，`fmtTime` 的注释也是按这个约定写的，所以真实接口不会出现 Z。
  - Z 只会来自 mock、测试，或者违反契约的上游。
  - 但 `fmtTime` 目前在约 60 个调用点上只是去掉 +08:00；遇到 Z，就会把 UTC 时间当成北京时间显示，属于静默出错。
  - t_view 已经用 `fmtShanghai` 自己换算，不受影响。
- **对旧调用点的影响**：输入是 +08:00 的，输出必须逐字节不变，现有用例全部不改；只有输入带其他偏移时才会换算。
- **T-F37 验收（G/W/T）**：
  1. Given 机器时区为 America/Denver，输入 `2026-11-10T02:31:00Z` / When `fmtTime` / Then 输出 `2026-11-10 10:31`。
  2. Given 输入 `2026-11-10T10:31:00+08:00` 和 `2026-11-10T10:31:05+08:00` / Then 输出与现行一致，分别是 `2026-11-10 10:31` 和 `2026-11-10 10:31:05`。
  3. Given 输入 `2026-11-09T19:31:00-07:00` 或带毫秒的 `...00.000Z` / Then 输出 `2026-11-10 10:31`。
  4. Given 输入非法字符串或只有日期 / Then 原样返回，与现行一致，不抛错。
  5. Given TZ 分别为 America/Denver、UTC、Asia/Shanghai / Then 1–4 的结果都一样。
- **T-F37 用例名**：`t-f37 fmtTime Z 结尾换算北京时间`、`t-f37 fmtTime +08:00 输出不变`、`t-f37 fmtTime 其他偏移换算`、`t-f37 fmtTime 非法输入原样返回`、`t-f37 fmtTime 与机器时区无关`。
- **范围**：只改 `lib/format` 的 `fmtTime`，可以复用 `fmtShanghai` 的写法，不改任何调用点。需要的话，可以让 `fmtShanghai` 改为调用 `fmtTime`，但不做其他重构。

### ③ fresh 但 gaps 非空时显示 GapNote：合适，保持

- **依据**：
  - api-contract §1.1 的示例本身就是 fresh 带 gaps（新闻 no_source）。
  - `/portfolio` 的 `exposure.sector` 缺口也不会降成 partial。
  - `GapNote` 对这种情况已经有「数据提示」标题，全站其他页面也是这样显示的。
- t_view 的契约（§3.7 ⑥，本单补充）：fresh 时后端输出的 gaps 应为空。万一不为空，前端照常显示原因，不隐藏。
- **对旧调用点的影响**：无，现行行为保持不变。

## 8. Codex 第二意见的复核

- Codex：L3 gpt-6.1-sol/high，用于评审第二意见；采纳 3 条，驳回 2 条。
- 运行方式：只读沙箱，在我自己的稀疏 worktree 里跑，只检出 src/frontend；契约只给了 §3.7 和 §10 的摘录，没给它密钥、麦蕊相关内容、private-samples 或股东代码。跑完 `git status` 是干净的，worktree 已删除。
- 它的原始输出存在 /workspace/team/reports/codex/T-A146/second_opinion.md。

| # | Codex 意见 | 我的复核 |
|---|---|---|
| 1 | `TodayFocusRow` 的 t_view 仍可缺省，没表达出「持仓行必带」 | **驳回**：类型系统没法按 holding 是否为空来区分；可缺省是后端还没升级时的保守处理，`TViewCell` 会按不可用显示。要表达这种区分就得引入判别联合，属于过度设计。 |
| 2 | `notApplicableText` 没复用 `isNotApplicable`，形成两套口径 | **采纳**（从契约侧解决）：按裁定 ① 修改 §3.7 ⑤；前端不返工。 |
| 3 | `availableBase` 用绝对值比较，base_qty 为负时漏判 | **采纳**：我核对了 `absAtLeast` 的实现，确有此问题，列为 S1 必改，不阻断。 |
| 4 | 非持仓行用 `?? null` 判断，不带字段也能通过 | **驳回**：T-A145 已裁定非持仓行不带字段等同于 null。 |
| 5 | 默认 mock 的 `typeof` 断言太宽 | **采纳**：列为 S3。 |
| — | 过度复杂化：无 | 同意 |
