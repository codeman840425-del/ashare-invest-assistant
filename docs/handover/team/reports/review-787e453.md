# 评审 787e453（前端 T-F23 裁定跟进，31 个文件）

- 评审人：项目架构师；时间：2026-11-01 20:45（America/Denver，UTC-7）
- 方式：只读。干净导出 git archive 787e453，`pnpm install --frozen-lockfile` 后跑 eslint、tsc、vitest、pnpm audit；没有推送。
- 对照：契约 v0.2.9 #30（§7.7B 计划/提醒、冲突证据、lot_rule、CSRF §1.3）、T-F23-rulings-frontend.md。

## 结论：可以推送，但必须和 d9c045f 一起推

本提交单独推上去时，vitest 有 1 个失败：`ERROR_CODES 与契约 §4 错误码表逐行一致`。原因是契约 4b40e5c 加了 414 URI_TOO_LONG，前端还没同步；紧接着的 d9c045f 就修了这个问题。所以不能停在本提交，至少推到 d9c045f。没有 B/M。

## 1. 实测

| 项 | 787e453 单独 | 带上 d9c045f |
|---|---|---|
| eslint | 0 | 0 |
| tsc | 0 | 0 |
| vitest | **src/api 有 1 个失败**（URI_TOO_LONG 缺失） | 39 个文件 / 621 passed，1 skipped |
| pnpm audit | 通过 | 通过 |

## 2. 核对

| 说法 | 核对 |
|---|---|
| 403 CSRF_FAILED 提示刷新 | ✓ src/api/errorPolicy.ts:117 返回 'csrf'；src/app/useApiErrorRedirect.ts:24 给出 csrfExpired |
| CSRF 白名单与 Origin（mock，契约 §1.3） | ✓ src/mocks/accountHandlers.ts:46 白名单只有 login、register；Origin 是外站 → 403；不带 Origin → 放行，和契约一致 |
| 冲突证据 signal.conflict_signal_id | ✓ src/pages/signals/CandidateSignalDetailPage.tsx:107–117，只取 active 的 STRATEGY_CONFLICT 原因，并去重 |
| lot_rule 读 details.fields[] | ✓ src/lib/planDraft.ts:58–64，只认 `field=chosen_qty, issue=lot_rule` |
| 研究候选改版带 Idempotency-Key | ✓ src/api/candidateQueries.ts:72–94：同一次操作重试复用同一个键；请求体变了、成功、或者服务端给出明确错误时换键 |
| plan-drafts 400 先于 409 | ✓（vitest 覆盖） |

## 3. 问题

**B：无。M：无。**

**m**
- m1 src/lib/planDraft.ts:33–34 在前端写死了整手参数（`/^68[89]\d{3}\.SH$/` → 买入最少 200、步长 1，其余 100/100）。这是前端自己的假设：应以服务端的 lot_rule（400 details）为准，问题 86 还没有核对。现在只用来做提示，所以不阻塞。修法：注释里写明"只是提示"（已经写了），并且一旦服务端返回 lot_rule，就以服务端的值覆盖本地值。→ 前端
- m2 CandidateSignalDetailPage.tsx:139 把 evidence 里取来的 id 直接拼进 `Link to=/candidate-signals/${id}`，没有校验它是不是 uuid。数据来自本系统，风险低，但建议先过一遍 uuid 正则，不合格就不渲染成链接。→ 前端
- m3 candidateQueries.ts:88–92：任何不是 NETWORK_ERROR 的 ApiError 都会换键，这也包括网关返回的 502/504（服务端可能已经处理完了）。按契约，重试 5xx 时应复用同一个键，否则可能重复创建。建议只在 4xx 时换键。→ 前端

## 4. 推送后 CI

| 任务 | 只推到本提交 | 推到 d9c045f |
|---|---|---|
| frontend（eslint/tsc/vitest/audit） | **红**（vitest 1 个失败，归前端） | 绿 |
| contract --meta-json | 红（后端 /meta/enums 还没同步，归后端 T-B50，d3be426 修复） | 红，同左 |
| backend / migrations | 不涉及 | 不涉及 |

## 5. 谁做什么
- 前端：m1–m3（不阻塞）。
