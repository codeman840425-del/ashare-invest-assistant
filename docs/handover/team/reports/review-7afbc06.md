# 评审报告：7afbc06（T-F13 盘后日报补全）

- 评审人：架构师（代审）
- 日期：2026-11-02
- 评审依据：契约 v0.2.7 §5.3 `DailyReport`、§1.2 游标分页、§7 `/daily-reports` 与 `/daily-reports/{date}`；自述 `reports/T-F13.md`
- 评审方式：只读。没有改代码，也没有提交。`git archive 7afbc06 src/frontend docs` 导出到 `/tmp/rv-7afbc06`，在导出目录做干净检出后跑全部脚本。

## 0. 干净检出

| 项目 | 结果 |
|---|---|
| 提交所在位置 | 本地 main 的 HEAD（父提交 c55a42e） |
| 改动范围 | 只改 `src/frontend`，共 7 个文件，+427 / −84 |
| `pnpm install --frozen-lockfile` | 通过 |
| typecheck | 通过 |
| `eslint . --max-warnings=0` | 通过 |
| test | 21 个文件通过，1 个跳过；345 个用例通过，1 个跳过（`tracked-sources` 跳过，已用 `git check-ignore --no-index` 补查，没有问题） |
| build | 通过 |
| check:dist | 通过：34 个文件，20 个示例标记 0 命中，各代码块都不超过 500 kB |
| 证书安全 | diff 中没有证书值或疑似子串，也没有密钥 |
| 作废内容 | 0 命中 |

说明：两个提交并行跑测试时，因为负载高有 3 个用例超时失败：t-f03、t-f08，以及本提交的 t-f13 “/daily-reports 跳到最新一期”。依次单独跑后全绿。t-f13 与 t-f24 一起又单独跑了 3 次，都是全绿，见 m5。

## 1. 结论

**通过。** 没有 B 级问题，也没有 M 级问题，只有 5 条 m 级问题。§5.3 的字段都用上了，未导入分支、筛选、键盘可达、免责提示也都实现了。

## 2. 重点核对

| 检查项 | 结论 | 说明 |
|---|---|---|
| 游标分页 | ✅ | 新增 `useDailyReportPages`（useInfiniteQuery），首页只带 `limit`，后续页带 `cursor=next_cursor`，`next_cursor=null` 时停止，与 §1.2 一致。缓存键与 `useDailyReports` 分开，不影响首页跳转。下拉末尾有“加载更早…”选项 |
| 上一期 / 下一期 | ✅（有 1 条 m） | 列表按日期倒序：idx+1 是上一期，idx−1 是下一期。最新一期时“下一期”禁用；已经到已加载列表的末尾但还有下一页时，点“上一期”会先加载更早的一页。当前日期不在已加载列表中时（深链），下拉里仍保留当前日期 |
| 对账 | ✅ | 显示状态标签、`diff_count`、`important_count`（“重要 N”）、`as_of`（“对账于…”）。状态为 diff 且有 `account_id` 时给出“查看对账”链接，指向 `/portfolio?tab=reconciliation&account_id=…`，持仓页支持这两个参数 |
| 未导入分支 | ✅ | `account=null` 时，如果 `reconciliation.status=not_imported` 显示“尚未导入交割单”，否则显示“未关联账户”，两种情况都给出 `/portfolio/import` 入口（路由存在），与 §5.3 “没有账户或未导入时 account=null” 一致。mock 加了一期上一期的示例数据覆盖这个分支 |
| 筛选 | ✅ | 由 URL `?filter=` 驱动，可选 all / changed（含新增和有变化）/ unchanged / removed。非法值按 all 处理，选“全部”时删掉参数，切换用 replace 不产生历史记录。每个选项带计数，筛选结果为空时有空态提示 |
| 键盘可达 | ✅（有 1 条 m） | 有 `suggestion_id` 的卡片是 `role=link`、`tabIndex=0`，按 Enter 或 Space 进入候选信号卡，有 focus-visible 样式；没有 `suggestion_id` 的卡片（含已移出）既不能点击也不能聚焦。参考区间条有 `role=img` 和 aria-label |
| 免责提示 | ✅ | 日报属于 ⚖ 接口，页头下方固定展示 `CardDisclaimer`；参考仓位区间注明“模板参数，不是指令” |
| 其他 | ✅ | 数据缺口逐条列出；市场宽度缺失时明确显示“缺失”；仓位标记用 clampPct 防止越界；日期不存在时显示错误，并给出回到最新一期的链接 |
| 上轮 m1（`/plans/{id}` 404） | ❌ 未处理 | PLACEHOLDERS 仍没有 `plans/:id`，见 m4 |

## 3. 问题

### B 级
无。

### M 级
无。

### m 级

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `DailyReportPage.tsx` `DateSwitcher` | 当前日期是已加载列表的最后一项、而且还有下一页时，第一次点“上一期”只会加载下一页，不会跳转，要再点一次才到上一期 | 在 `fetchNextPage()` 完成后，取新一页的第一项直接跳转 |
| m2 | `DateSwitcher` | 切换日期时 URL 上的 `?filter=` 会丢失，筛选重置为“全部” | 看产品意图决定：如果希望保留，跳转时带上当前的 search |
| m3 | `StockCard` | 卡片用 `aria-label` 覆盖了整张卡的可读名称；内部的证据标签只能用鼠标悬停查看，键盘看不到（这是 EvidenceChips 的原有问题） | 改用 `aria-labelledby` 指向标题；证据标签后续改成可聚焦的元素 |
| m4 | `app/routes.tsx` | 上轮的 m1 仍未处理 | 同 review-8249d6e m4 |
| m5 | `t-f13.test.tsx` 及原有的 t-f03、t-f08 | 在高负载下按默认超时会偶发失败；单独跑则稳定 | 给异步断言统一设一个更宽的 `findBy` 超时，或在 CI 中限制 vitest 的并发数 |

## 4. 待对齐（不算本提交的缺陷）

1. 契约没有写明 `/daily-reports` 列表的排序：§1.2 的默认是 `created_at desc`，本接口也没有另行注明。前端假定按 `date desc`，需要由架构师在契约中写明“按 date 倒序”。
2. 日报 `pending.plan_drafts` 和 `pending.active_reasons` 的统计口径与前端去向未定义。前端暂时用 `/plan-drafts?status=pending` 和 `/candidate-signals?state=blocked`，目标页目前仍是占位页。建议在契约中补一张去向表（自述遗留问题第 1 条）。
3. plan 2.1 提到的“集中度”在 §5.3 中没有对应字段（自述遗留问题第 2 条）。
4. 列表接口没有按日期定位的参数，深链很早的日期时，需要一页页加载才能找到相邻的期（自述遗留问题第 3 条）。
5. v0.2.8 未同步：本提交按 v0.2.7 评审，v0.2.8 中与日报无关的条目另行安排。

## 5. 推送建议

本提交没有 B 级问题，干净检出全绿，**可以推送**。推送 main 时会一起带上还没评审的 457a211、116cb7e、c55a42e（后端）和 307132b（docs），请先完成这几项评审，或者由用户确认。
