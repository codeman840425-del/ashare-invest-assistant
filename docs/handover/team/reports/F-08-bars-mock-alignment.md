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

`pages/pool-f08-bars-mock-alignment.test.tsx`：迁移 F-08 新增 8 例；`pages/t-f08.test.tsx` 按 origin/main 原 blob 恢复，全部历史用例保留。

## 验证
- 2026-11-11 11:14 MST：`vitest run src/pages/t-f08.test.tsx --reporter=verbose` exit 0，实际 **16/16**（原派单称13例，另有3条契约相关测试，未跳过）；`pool-f08-bars-mock-alignment.test.tsx` **8/8**，exit 0。
- `tsc --noEmit -p tsconfig.test.json` exit 0；`pnpm run build` exit 0。原始日志：`F:\workspace\team\reports\F-08c-evidence\`。
- `t-f08` 对 main blob 一致，历史测试删除/改写 **0**；#86 的 handlers blob 原样承接（仅相对原#57去重一块注释），8条新测试迁入 pool 文件；#86原报告归档到上述证据目录，旧报告关于向 t-f08 追加的说法作废。
- 最终完整PR范围扫描与diff检查结果以#57修复提交评论为准，不复用旧扫描计数。
- **既有失败已隔离**：`src/mocks/contract.test.ts` 的 `Notification` 用例在**干净基线**上同样失败（stash 前后对照），与本单无关，未修（越界），移交记录

## 移交项
- **#19 合入后需要接续单**：删 `STOCK_SUB_PATHS_PENDING` 的 bars 行 + 用 `isSuperseded()` 覆盖 bars 的 404 展示。本单已把 mock 语义备好，接续单只需改判定与断言。
- `contract.test.ts` 的 Notification 既有失败需另一单处理（非前端 mock 语义问题）。
- DeepSeek：未用，原因：语义对齐需逐条对照后端实现，不外包。
