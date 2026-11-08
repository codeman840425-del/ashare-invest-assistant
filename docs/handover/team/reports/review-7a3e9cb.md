# 评审 7a3e9cb（前端：契约 v0.2.9 同步，T-A10 P01–P21）

- 评审人：架构师；写于 2026-11-02 09:47 北京时间；只读评审。
- 依据：docs/api-contract.md v0.2.9（变更表 #1–#28）、reports/T-A10-pending.md、T-A10-frontend.md。

## 结论：**通过**（无 B、无 M；有 5 个 m，其中 2 个依赖本轮裁定，见 frontend-pending-rulings.md）

## 逐项核对
| 项 | 结果 | 位置 |
|---|---|---|
| `/candidate-signals/{id}/events` 改 §1.2 分页 `{items,next_cursor}` | 符合：`useCursorPages`；mock 按 `at desc, id desc` | api/signalQueries.ts；mocks/signalHandlers.ts |
| discard 请求体 `{}` | 符合：`discard.mutate(undefined)` → 发 `{}`；详情页删去备注框 | api/planQueries.ts；pages/plans/PlanDraftDetailPage.tsx |
| `/non-executable-reasons` 的 status 默认 active | 符合：一般查询不带 status（=active）；需要全部时显式 `status:'all'`（useSignalReasonsAll、queries.ts:157 建议原因）；mock 非法值 400 | api/queries.ts:89、:157；api/signalQueries.ts |
| `candidate_signal_event_cause` 6 值 | 与契约 §3 第 396 行逐项一致、顺序相同 | api/enums.ts；i18n/signalLabels.ts CAUSE_TEXT |
| CONTRACT_VERSION | `'v0.2.9'`；AppShell 横幅改读常量 | api/enums.ts；app/AppShell.tsx |
| P01/#1 可转债持仓 | `security_type|null`、`estimated`、`pnl*` 可空；null 类型不链接、estimated 显示“估算” | api/types.ts；pages/portfolio/* |
| P05/#5 名单类原因不可手动解除 | VIA_RESTRICTIONS 含 BLOCKLISTED、USER_MUTED；mock release → 409 | features/signals/signals.ts；mocks |
| P08/#7 冲突按原因码 | useConflictSignalIds 每批 ≤100、`code=STRATEGY_CONFLICT` | api/signalQueries.ts |
| P12/#13 多信号草案 | mock 同向校验 400、反向冲突 409 | mocks/planHandlers.ts |
| P13/#14 lot_rule | mock 400 用 fields[] 形式；前端两处都读 | mocks/planHandlers.ts；features/plans |
| 其他 P（tracking `scope:'mine'`、NonExecutableReason 加 security_code/name、resume 无变化不写日志） | 符合 | — |

## 问题
- B：无。M：无。
- m1 注释仍写 v0.2.8：src/frontend/src/main.tsx:17、mocks/handlers.ts:2、mocks/accountHandlers.ts:3、api/planQueries.ts:1、api/planTypes.ts:1、pages/plans/PlanDraftDetailPage.tsx:22、PlanDraftsPage.tsx:15。
- m2 CandidateSignalsPage“今日已解除”页签不再显示 `strategy_name`（回归，信息变少）。
- m3 lotWarning 在 `lot≤1`（科创板）时不检查起买量 200（前端提示缺失，服务端仍会 400）。
- m4 Conflicts 区按方向推断对方信号（待定 2）。本轮裁定已写明 evidence 字段，前端改读 `STRATEGY_CONFLICT` 原因的 evidence。
- m5 mock 创建事件 cause 用 `executability_check`（待定 1）；本轮裁定与之一致，无需改，只需补注释引用裁定。

## 测试（干净导出，串行，跑完已删）
| 项 | 结果 |
|---|---|
| typecheck | rc=0 |
| lint | rc=0 |
| vitest | 32 个文件通过 + 1 跳过；485 通过 + 1 跳过（共 486） |

## 谁需要做什么
- 前端：m1–m4（m4 按裁定 2 改读 evidence；m3 按裁定 7 补科创板起买量提示）。
- 后端：按裁定 1、2、5、6 实现 cause、evidence 字段、lot_rule details、校验先后。
