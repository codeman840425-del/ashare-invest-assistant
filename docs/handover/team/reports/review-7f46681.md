# 评审 7f46681（前端 T-F24：review-5969886 跟进，7 个文件）

- 评审人：项目架构师；时间：2026-11-01 20:55（America/Denver，UTC-7）
- 方式：只读。干净导出 git archive 7f46681，`pnpm install --frozen-lockfile` 后跑 eslint、tsc、vitest、pnpm audit；没有推送。
- 对照：契约 v0.2.9 #31（①–③）、review-5969886.md。按父代理的说明，契约缺口（T-F23-rulings-frontend 第 9 项、心跳字段、master.* 告警文案、days_left 为 null）另有人裁定（0edb298 已出 #37–#40，本提交早于它）。前端对这些缺口自己做的假设一律记为 m，不阻塞。

## 结论：可以推送

没有 B/M，四项检查全绿。

## 1. 实测
| 项 | 结果 |
|---|---|
| install / eslint / tsc / audit | 全部 rc 0 |
| vitest | 40 个文件 passed，1 个 skipped；633 passed，1 skipped |

## 2. 核对
| 说法 | 核对 |
|---|---|
| ① 没有现金记录的账户 data_status=partial | ✓ src/mocks/handlers.ts:168–170（契约 #31 ①：除 exposure.sector 之外的任何缺口都会降级） |
| ② horizonDataMissing 硬门槛优先 | ✓ src/i18n/horizonCaps.ts:40：已经被 gate 封顶的周期不再算"数据不足"，noSuitableForLackOfData 基于它判断，符合 #31 ③ |
| ③ 告警用 licence.expiring、每个 key 一条、固定文案、排序 | ✓ src/mocks/ingestAlerts.ts：文案与契约第 1033 行 #31 ② 一致；同一个 key 只留一条，有 critical 时升级；licence.expiring 的条件是 0 ≤ days_left ≤ 14 且状态不是 expired（:86） |
| ④ freshness 显示数据集中文名 | ✓ 新增 src/i18n/ingestLabels.ts（INGEST_DATASET_NAME） |
| ⑤ React key 防御、heartbeat mock 场景 | ✓ src/pages/admin/AdminIngestPage.tsx:51 用 `${a.key}-${i}` 作为 key，并保持服务端给的顺序；setMockIngestHeartbeat（ingestAlerts.ts:46） |

## 3. 问题

**B：无。M：无。**

**m（前端对契约缺口自己做的假设，不阻塞）**
- m1 心跳：ingestAlerts.ts:43–63 自己定义了 fresh/stale/unknown 三种心跳状态，只要不是 fresh 就出 critical 告警，文案是"采集主实例心跳超时"。契约当时没有心跳字段；以 0edb298 的 #38/#39 为准，下一轮对齐。→ 前端
- m2 days_left 为 null：:86 遇到 null 时不出 licence.expiring。这是前端自己的假设，以裁定结果为准。→ 前端
- m3 master.* 和未知 key 的排序：:53 `KEY_ORDER.indexOf(group)` 对不在表里的 key 返回 -1，所以 master.* 或未知 key 会排到最前面。只影响 mock；master.* 的文案另有裁定。建议找不到时排到最后（用 KEY_ORDER.length）。→ 前端
- m4（nit）:92 errors.* 的子排序用的是 localeCompare，不是严格的码点升序。和服务端的排序可能有细微差别，只影响 mock。→ 前端

## 4. 推送后 CI
| 任务 | 结果 | 归属 |
|---|---|---|
| frontend | 绿 | — |
| contract --meta-json | 绿（前提是 d3be426 已在它之前推上去） | — |
| backend / migrations | 不涉及；backend 的 pytest 情况同 review-d018fad | tester |

## 5. 谁做什么
- 前端：m1–m4，按 0edb298 的 #37–#40 对齐（下一个提交 a2d2b74、d860970 是否已经对齐，还没有评审）。
