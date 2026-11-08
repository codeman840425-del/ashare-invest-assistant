# 评审报告：前端 d26e1d3（管理端数据证书列表与暂停/恢复）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 被评审提交：`d26e1d3`（2026-11-02 08:20 北京时间），父提交为 53468a5。
  - 只改 `src/frontend/`，共 12 个文件，+604/−18 行。
  - 自述见 `T-F22-admin-licences.md`。
- 评审依据：
  - HEAD 上的 `docs/api-contract.md`（v0.2.9，687159f）：§5.1 `DataLicenceStatus`、`AdminDataLicence`、`IngestLicenceStatus`；§7.9 `GET /admin/data-licences`、`POST …/pause|resume`；§1.3 管理端 404 规则；v0.2.8 #12、#14、#17⑤（重复暂停幂等）；v0.2.9 #5（P04–P06）。
  - 本提交自述对齐的版本是 v0.2.8。v0.2.9 是在本提交之后才发布的，它的 #5 写明“契约不改”，所以这里一并按 v0.2.9 核对。
  - 自述中的“遗留问题 1–5”属于契约待定项，本次不作裁定。
- 本次只读：没有改代码，没有提交，没有推送；主工作树没有动过。

## 0. 干净检出结果

方法：`git archive d26e1d3 src/frontend docs | tar -x -C /tmp/rv9/d26e1d3`，然后在 `src/frontend` 下依次执行下表各步，单独串行运行。环境：Node v24.22.1（CI 用 22）、pnpm 10.34.6。

| 步骤 | 命令 | 结果 |
|---|---|---|
| install | `pnpm install --frozen-lockfile` | rc=0，lockfile 未变 |
| typecheck | `pnpm run typecheck`（app、node、test 三个 tsconfig） | rc=0 |
| lint | `eslint . --max-warnings=0` | rc=0，0 警告 |
| test | `pnpm run test` | rc=0：Test Files 27 passed / 1 skipped（28）；Tests 422 passed / 1 skipped（423） |
| build | `pnpm run build` | rc=0 |
| check:dist | `pnpm run check:dist` | rc=0：dist 共 47 个文件，21 个示例标记 0 命中；业务代码块均 ≤ 500 kB |
| 被忽略的已跟踪文件 | `git ls-tree -r d26e1d3 src/frontend \| git check-ignore --no-index --stdin` | 0 命中 |

- 跳过的 1 个测试文件是 `tracked-sources.test.ts`：导出目录里没有 `.git`，它按设计跳过，上表最后一行就是替代它做的检查。
- 测试总数 423 与自述一致。新增的 `t-f22-admin.test.tsx` 有 14 个用例。

## 1. 结论：**通过**

没有 B 级或 M 级问题。m 级问题见第 7 节。

## 2. §7.9 / §5.1 证书列表与按证书的采集状态（licence_id）

- **类型**：`AdminDataLicence extends DataLicenceStatus`，再加上 `licence_id: string | null`、`user_id`、`username`、`display_name`、`per_minute_limit`、`calls_last_minute`、`calls_today`、`queue_depth{p0,p1,p2}`。与 §5.1 逐字段对应，没有多出或缺少的字段。用例 38 断言了字段集合完全相等。
- **列表**：
  - 用 `useCursorPages` 按 §1.2 游标分页，`limit=50`，去重键为 `user_id`。
  - 契约没有定义筛选参数，所以请求只带 `limit` 和 `cursor`。页面上的“全部 / 管理员已暂停 / 异常 / 未设置”是本地筛选，只作用于已加载的行，旁边写明了“接口未提供筛选参数”。
- **每位用户一行，包括未设置证书的用户**：未设置时 `licence_id=null`，状态为 `not_set`。这符合 §7.9 中“全部用户”的要求。
- **与 `/admin/ingest/status` 一致**：mock 中两个接口共用 `licenceMetrics`，同一证书的 `licence_id`、今日调用、队列、上限都相同，对应 §9 v0.2.8 第 2、4 条，用例 52 有覆盖。
- **暂停期间删除证书**：列表仍显示 `paused_by_admin`，`licence_id=null`，并加“证书已删除”标记；恢复后变为 `not_set`。与 §7.9（v0.2.8）一致。原 mock 在这种情况下返回 `not_set`，本提交已改正。

## 3. 暂停与恢复

| 要求（§7.9 及 v0.2.8 #17⑤） | 实现 | 结论 |
|---|---|---|
| 请求体 `{reason: string(1–200)}`，reason 必填 | 弹窗中理由必填：去掉首尾空白后长度为 1–200 才能提交，`maxLength=200` 并显示字数；同时必须勾选“我已核对…用户 xxx”。两项都满足，“确认”按钮才可点。提交的是去掉首尾空白后的理由。mock 对空理由或超过 200 字返回 400（用例 87、112） | ✅ |
| 成功返回 204 | 客户端 `request` 对 204 返回 undefined。成功或失败后都重新拉取 `['admin','data-licences']` 和 `['admin','ingest']`，以服务端状态为准 | ✅ |
| 重复暂停幂等：已暂停（不论证书是否已删除）→ 204，状态不变，不写审计 | mock 的 `adminPause` 对已暂停用户直接返回 ok，不写日志；用例 62 断言了 204、状态不变、审计条数不变。界面上已暂停的行只显示“恢复”，不会主动重复暂停 | ✅ |
| 未暂停且未设置证书 → 409 `DATA_LICENCE_NOT_SET` | mock 对 pause 和 resume 都返回 409（用例 72）。界面上 `not_set` 行没有操作按钮，只有一个悬停说明。列表过时导致收到 409 时，弹窗内显示管理端文案“该用户没有设置数据证书，也不在暂停中，无法操作；列表已刷新”，而不是面向用户本人的“去设置”（用例 141） | ✅ |
| 恢复后为 `pending_verification`；证书已删除时恢复后为 `not_set` | mock 实现了这两种情况，弹窗里的影响说明也按情况区分（用例 62、80、130） | ✅ |
| 写审计 | 由后端负责；弹窗中提示“操作会写入审计” | ✅ |

## 4. T-A10（v0.2.9 #5，P04–P06）互跳与截断链接

- **P04 页面**：新增 `/admin/data-licences`，“更多”菜单和用户菜单中都加了“数据证书（管理）”入口。
- **P05 截断链接**：`licences_truncated=true` 时，提示文字由纯文本改为 `<Link to="/admin/data-licences">`，测试标识为 `ingest-to-licences`。
- **两页互跳**（v0.2.9 #5 说明互跳是可选项）：
  - 采集状态页的用户名链接到 `/admin/data-licences?user=<user_id>`，证书列表会高亮该行（用例 163）；
  - 证书列表页顶部有回到采集状态页的链接。
  - 用的是 `user_id` 而不是 `licence_id`。两页都是每位用户最多一张证书，所以二者等价，而且对已删除证书的行也适用。
- **P06 暂停界面**：见第 3 节。

## 5. 证书安全

- **页面**：列表只渲染显式声明的列（用户、状态、档位、到期、最近验证、调用量、队列、熔断至、最近错误、操作）。弹窗只显示用户名和状态。没有任何证书值、掩码、末几位、长度或指纹相关的列或文案。
- **类型**：类型定义中没有 `licence`、`masked`、`last4`、`digest` 之类的键。即使后端多返回了字段，也不会显示出来。
- **mock**：mock 内部的 `digest` 字段是示例占位串，不会进入任何响应。用例 38 断言每一行序列化后都不含 `licence"`、`masked`、`last4`、`digest`。
- **新增行检索**：在新增行中搜索 fingerprint、mask、last4、suffix、“末几位”“后四位”、hmac、≥32 位十六进制串，命中的只有上面这条测试断言本身，业务代码 0 命中。`check:dist` 的示例标记在产物中 0 命中。
- **已作废内容**：在新增行中搜索 consent、risk_assessment、`fit_ack`、`/onboarding`、`me/export`、`PROFILE_OR_CONSENT`，0 命中。新增的 `console.log` 只出现在截图脚本中。

## 6. 管理端路由的权限守卫

- **路由**：`/admin/data-licences` 采用懒加载，外层包了 `AdminGate`。`AdminGate` 只对 `role=admin` 渲染页面，其他情况（包括 `/me` 请求失败）一律显示 404 页，与 §1.3 中后端对非管理员返回 404 的做法一致。用例 96 覆盖了这一点。
- **路由顺序**：该路由排在 `admin/*` 兜底路由之前，所以不会落到占位页。
- **入口**：菜单入口只对管理员显示。接口层面，普通用户访问时 mock 返回 404（用例 34），列表请求设置了 `retry:false`。

## 7. 问题清单

| 级别 | 编号 | 问题 | 归属 |
|---|---|---|---|
| B | — | 无 | — |
| M | — | 无 | — |
| m | m1 | “到期”列对已过期证书显示“剩 -N 天”，`days_to_expiry` 为负。与 review-9547181 的 m5 是同一类问题，建议两页一起改为“已过期 N 天” | 前端 |
| m | m2 | 从采集状态页跳到 `?user=<id>` 时，如果目标用户不在已加载的第一页（50 行）里，高亮就看不到，页面也不会提示或自动加载更多。用户多时，互跳实际上会失效 | 前端 |
| m | m3 | mock 校验 `reason` 时用的是原始长度，没有去掉首尾空白，所以纯空格的理由在 mock 中能通过。前端提交的是去掉空白后的值，不受影响。契约只写了 `string(1–200)`，没有写是否去空白，实际以后端为准 | 前端 |
| m | m4 | 本地筛选只作用于已加载的行，页面已经写了说明。服务端筛选参数属于自述遗留 2，等契约补充后再改 | 前端（等契约） |
| 记录 | — | 本提交的 `CONTRACT_VERSION` 仍是 v0.2.8，v0.2.9 在本提交之后才发布，所以不算缺陷。按 v0.2.9 #12，`/non-executable-reasons` 的 `status` 默认值已写明为 `active`，需要展示已解除原因的地方要传 `status=all`。这不属于本提交范围，但请前端在同步 v0.2.9 时处理（对应 review-b34260f m1） | 前端 |
| 记录 | — | 自述遗留 1–5（对已设置但未暂停的用户调用 resume、列表筛选与排序、暂停理由不可见、冷却期不可见、暂停后是否通知用户）均为契约待定项，本次不裁定 | 架构师 |
