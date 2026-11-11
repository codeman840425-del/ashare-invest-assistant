# F-08 bars mock 对齐后端 B-04 真实语义

基线 `origin/main=465e020`，分支 `ds/F-08`，不叠加 #19/#49。**依赖 #56（B-04）合入**。

## 开工前的口径修正（重要）
派单原写「删 STOCK_SUB_PATHS_PENDING 的 bars 行」。实际核对 main：**该清单由 #19（T-F34b）引入，尚未合入**，main 上不存在，无行可删。同样 `isSuperseded()` / `isStockSubPending()` 也不在 main 上。

因此本单聚焦 main 上**真实存在**的缺口：**mock 与后端 B-04 的语义不一致**——这正是 B-03 草稿第 1 条形状差异指向的问题。

## 改动（src/frontend/，2 文件）
`mocks/handlers.ts` 的 bars handler：
1. **旧代码 → 404 + `details.superseded_by`**：从示例档案 `code_history` 惰性推导映射（模块顶层求值会撞导入顺序导致表为空——这是实测踩到的坑），对齐后端查 `security_code_history`。
2. **补 `from`/`to` 日期窗过滤**：原 mock 未实现，契约 §7.3 有。
3. **日期窗内无数据 → 对齐后端 `empty_bars()`**：`200 + unavailable + no_source + data_as_of=null`，不是 404、不编造时间。
4. **停牌 ≠ 无源**：停牌证券保留历史 K 线与 `data_as_of`，测试专门守住这条，避免误清空。

`pages/t-f08.test.tsx`（新）：8 例。

## 验证
- `t-f08` **8/8**；`t-f03`（含个股/市场）**14/14**
- `secret_scan` 2 文件 0 命中；`git diff --check` 干净
- **既有失败已隔离**：`src/mocks/contract.test.ts` 的 `Notification` 用例在**干净基线**上同样失败（stash 前后对照），与本单无关，未修（越界），移交记录

## 移交项
- **#19 合入后需要接续单**：删 `STOCK_SUB_PATHS_PENDING` 的 bars 行 + 用 `isSuperseded()` 覆盖 bars 的 404 展示。本单已把 mock 语义备好，接续单只需改判定与断言。
- `contract.test.ts` 的 Notification 既有失败需另一单处理（非前端 mock 语义问题）。
- DeepSeek：未用，原因：语义对齐需逐条对照后端实现，不外包。
