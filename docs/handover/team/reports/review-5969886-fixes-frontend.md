# T-F24 review-5969886 跟进（前端）

- 提交：`7f46681`（2026-11-02 10:52 北京时间），只含 src/frontend/ 下 7 个文件；只在本地提交，未 push
- 依据：契约 v0.2.9 #31（docs 66f0c79、1d02980）、reports/review-5969886.md ①–⑤
- 校验：工作区 typecheck 0 / eslint 0 / vitest 41 文件 634 用例全部通过；**干净检出（HEAD=7f46681）cleanci rc=0**，634/634，check-dist 0 命中（反向自检有效）；pnpm audit「1 moderate」是原有的，不是本次引入
- 扫描（暂存内容）：gitleaks no leaks、secret_scan 阻断 0 / 警告 0、禁用词与 11 位数字 0 命中
- 截图：reports/review-5969886-fixes-frontend/ingest.png（1440×900 深色，console 错误 0，外部请求 0）

## 逐项结果
| 项 | 结果 | 位置 |
|---|---|---|
| ① 无现金记录账户 data_status | mock 其他账户改为 `partial`（#31 ①：除 exposure.sector 外任一缺口都算 partial），相关断言已同步 | mocks/handlers.ts（1 块）、pages/t-b46-47.test.tsx |
| ② horizonDataMissing 硬门槛优先 | 某周期有 gate 类 cap 时不再算“数据不足”；整体“数据不足”= suitable 为空，且至少一个周期满足 horizonDataMissing。已补用例 | i18n/horizonCaps.ts |
| ③ 告警 | 新增 licence.expiring（status≠expired 且 0≤days_left≤14）；每个 key 只出一条，同时满足两级时只留严重；全部用 #31 固定文案；排序为 严重→警告 → 固定 key 顺序 → errors 按 upstream_code 升序 / freshness 按固定数据集顺序；leader 为 null 时只出 leader，不出 heartbeat | mocks/ingestAlerts.ts |
| ④ freshness 中文名 | 实时行情、分钟线、日线、财务数据、公告、证券主数据 | i18n/ingestLabels.ts、AdminIngestPage.tsx |
| ⑤ 可选 | 告警 li 的 key 改为 `${key}-${i}`，用作 React key 防御（另有用例渲染重复 key）；heartbeat 的 mock 场景（fresh/stale/unknown）通过 `setMockIngestHeartbeat()` 切换。未新增心跳时间字段（遵循 #31 ⑤） | AdminIngestPage.tsx、mocks/ingestAlerts.ts |

测试：pages/t-f24-review-fixes.test.tsx 覆盖 ①–⑤。

说明：告警文案是契约固定文案，所以不再加“（示例）”后缀；整页仍在“示例数据”横幅下。

## 他人改动
mocks/handlers.ts 在本次修改前没有未提交改动；mocks/fixtures.ts 本次未改动。用 git diff 确认暂存内容只有我的 1 块。

## 缺失的契约项（请编排者转给架构师）
1. /admin/ingest/status 的响应里没有心跳状态字段，前端无法直接判定 heartbeat 是 stale 还是 unknown。目前 mock 用 setter 模拟，需要契约说明 alerts 中 heartbeat 由后端产出，还是前端可以读到哪个字段。
2. master.* 告警 key（T-A04 #33）不在 #31 的范围内，前端没有做，等契约给出文案和排序位置。
3. licence.expiring 中 days_left 为 null（未填到期日）的情况，契约没有写明；前端按“不告警”处理。
4. （可选，未做）SuggestionDetailPage nit2 的数据来源注释：评审标为可选，留给后续。

## 需要谁做什么
- 架构师：补齐上面 1–3 项的契约。
- 后端：/admin/ingest/status 的 alerts 按 #31 去重和排序（前端 mock 已对齐，可用来对照）。
- 编排者：安排上面几项。
