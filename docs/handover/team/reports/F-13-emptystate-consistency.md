# F-13 空态展示一致性巡检（五子资源端点）

基线 `origin/main=465e020`，分支 `ds/F-10`（F-12 之后接续）。

## 一、发现（按严重度）

### 🔴 P0：`fmtTime(null)` 抛错导致整页白屏（已修）
`MarketPage.tsx:29` 直接 `fmtTime(m.data_as_of)`，而 `lib/format.ts` 的 `fmtTime` 首行就是 `t.endsWith(...)`。契约 T-A53 允许空数据时 `data_as_of` 为 null → **`TypeError: Cannot read properties of null (reading 'endsWith')` → React Router ErrorBoundary 整页崩**。
实测路径：`/market` + `data_as_of=null` 的响应。这是白屏级缺陷，且**与类型无关**（main 上类型仍非空，但运行时后端会给 null），不能等 F-07/#54 才修。

**修复**：`fmtTime(t: string | null | undefined)` 对 null/undefined/空串返回空串、不抛错；MarketPage 在 null 时不渲染「更新于」标签（避免空串变成悬空标签）。

### 🟡 P2：null 文案三种口径并存（本单只提建议，不改设计）
| 位置 | null 时表现 |
|---|---|
| `DataStatusTag` / `GapNote` | **省略时间行**（不显示「数据时间」） |
| 日报页 | 「—（无来源）」 |
| 市场页（F-07 加） | 「数据不可用（无数据时点）」 |
| 因子页签（F-10 加） | 「未知」 |

**统一口径建议**：
1. **底线（已写成测试）**：null 一律不得出现字面量 `null`/`undefined`/`Invalid Date`/`1970` 或编造的时间。
2. **上下文可以有不同措辞**：`data_as_of` 用「—（无来源）」或省略行；业务字段（如 `trade_date`/`factor_set_version`）用「未知」。不建议强行统一成一个词——「无来源」和「未知」语义不同，硬统一反而丢信息。
3. 建议后续把「null 不渲染悬空标签」抽成公共工具（如 `optionalMeta(label, value)`），避免每个页面各写一遍 `x ? ... : null`。

## 二、改动（src/frontend/）
- `lib/format.ts`：`fmtTime` 加 null/undefined/空串防护（**白屏级修复**）。
- `pages/market/MarketPage.tsx`：`data_as_of` 为 null 时不渲染「更新于」。
- `pages/t-f13.test.tsx`（新，7 例）：共享组件 null 行为、市场页不崩、`fmtTime` 防护、因子页签「未知」、日报页底线。

## 三、验证
- `t-f13` **7/7**（无 unhandled error）
- 回归 `t-f03`+`t-f10` **23/23**；`t-f03`+`t-f10`+`p2n05-daily` **74 passed / 2 skipped**
- `tsc --noEmit` **0**
- 扫描与 diff --check 随提交执行

## 四、移交项
- P2 的统一措辞属产品口径，按建议 2 保持上下文差异；若要硬统一请先给裁定。
- 测试里的图表组件必须 mock（`lightweight-charts` 在 jsdom 无尺寸会抛 `Value is null`），已按其他测试的写法补上。
- DeepSeek：未用，原因：需逐页核对实现并实测崩溃路径，不外包。
