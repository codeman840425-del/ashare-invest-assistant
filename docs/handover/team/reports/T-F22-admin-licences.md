# T-F22 遗留：管理端数据证书列表 /admin/data-licences + 暂停 / 恢复

- 提交：`d26e1d3`（只含 `src/frontend/`，12 个文件，本地提交，未 push）
- 依据：契约 v0.2.8 §5.1 `AdminDataLicence`、§7.9 `GET /admin/data-licences`、`POST /admin/data-licences/{user_id}/pause|resume`；补充裁定（67d123a）与 T-B03e（be607b3）：重复暂停幂等、暂停期间删除证书的处理
- 顺带解决 T-A09-frontend 遗留 4（没有 /admin/data-licences 页面、两页不能互跳）、5（截断提示没有链接）、6（管理端没有暂停界面）

## 做了什么

| 项 | 内容 |
|---|---|
| 页面 | `pages/admin/AdminDataLicencesPage.tsx`，路由 `/admin/data-licences`（AdminGate，非管理员显示 404 页）；“更多”菜单与用户菜单加“数据证书（管理）” |
| 列表 | 每位用户一行（含未设置证书的用户）：用户、状态、档位（+量化Pro）、到期（剩余天数）、最近验证、今日调用、近 1 分钟 / 上限、队列 P0/P1/P2、熔断至、最近错误、操作。§1.2 游标“加载更多”（`lic-pager`，每页 50）。不显示、也拿不到证书值或任何片段 |
| 操作 | 已设置且非暂停 → “暂停”；`paused_by_admin` → “恢复”；`not_set` → 无按钮（悬停说明）。暂停期间删除了证书（`paused_by_admin` 且 `licence_id = null`）→ 状态旁加“证书已删除”标记 |
| 二次确认 | 点按钮后弹窗：①说明影响（暂停：采集不再用该证书，用户替换 / 删除证书不解除，只有管理员恢复才解除；恢复：变为“验证中”并重新验证；证书已删除时说明恢复后为“未设置”）；②必填理由（去首尾空白后 1–200 字，`showCount`，写入审计）；③勾选“我已核对：要暂停/恢复的是用户 xxx 的数据证书”。理由和勾选都满足才能点“确认暂停 / 确认恢复”（暂停按钮为危险色） |
| 结果 | 成功后关闭弹窗、顶部提示“已暂停 / 已恢复 …”，并重新拉取列表与 `/admin/ingest/status`，以服务端状态为准（重复暂停是 204 无变化，界面也不会自作主张改状态） |
| 错误 | 错误显示在弹窗内（`lic-error`）。`409 DATA_LICENCE_NOT_SET` 用管理端文案“该用户没有设置数据证书，也不在暂停中，无法操作；列表已刷新”（不用面向用户本人的“你还没有设置 / 去设置”）；其他错误走 `errorText` |
| 筛选 | 本地筛选“全部 / 管理员已暂停 / 异常 / 未设置”，只作用于已加载的行，并在旁边写明“接口未提供筛选参数” |
| 互跳 | 采集状态页：用户名链接到 `/admin/data-licences?user=<user_id>`，列表高亮该行；截断提示改为链接；证书列表顶部链接回采集状态 |
| Mock | `GET /admin/data-licences`（全部用户，`created_at desc, id desc`，分页）；`POST …/pause|resume`（理由校验 400、用户不存在 404、未设置 409、其余 204）。调用量 / 队列与 `/admin/ingest/status` 共用一个函数，同一证书数值一致（§9 v0.2.8 第 2 条）。v0.2.8 行为：暂停按用户记录，PUT / DELETE 不解除；重复暂停 204 不变、不记审计；暂停期间删除证书后 GET 仍为 `paused_by_admin`（字段为 null），恢复 → 204，之后为 `not_set`。示例：`rejected_user` 为“暂停期间删除了证书”的样本（该账号不能登录，不影响其他页面） |
| 修正 | 原 mock 在暂停期间 DELETE 后 GET 返回 `not_set`，与 v0.2.8 不符，已改为 `paused_by_admin` |

## 测试与检查

- 新增 `src/pages/t-f22-admin.test.tsx` 14 例：非管理员 404；字段集合与 `AdminDataLicence` 完全一致、无证书值 / 片段；`not_set` 行 `licence_id = null`、`per_minute_limit = 0`；与 ingest/status 的 `licence_id`/今日调用/队列/上限一致；暂停 → 重复暂停（204、审计条数不变）→ 恢复为验证中；未设置用户 pause/resume → 409；暂停期间删除 → 恢复 → `not_set`；理由空 / 超 200 → 400，用户不存在 → 404；页面：未设置无按钮、删除标记、确认按钮在理由（纯空白不算）和勾选前禁用、暂停后状态与按钮变化、恢复已删除证书、409 管理端文案、本地筛选说明、采集页跳转高亮
- 全量：typecheck、eslint 0 警告、vitest 28 文件 423 例全过
- 干净检出 CI 步骤（`/tmp/cleanci.sh`）rc=0：pnpm audit 1 moderate（与之前相同）、check-dist 示例标记 0 命中、ignored-sources 错误 0（告警 4 为既有）
- secret_scan（工作区 196 个文件版本、暂存 12 个）阻断 0 警告 0；gitleaks 工作区 / 暂存均 no leaks；禁用词与 11 位数字扫描 0 命中；`git diff --cached --stat` 只含 `src/frontend/`
- 截图（`scripts/screenshot-admin-licences.mjs`，vite preview <host>:4184，1440×900 深色，外部请求 0、控制台错误 0）：`T-F22-admin-licences/01-admin-licences.png`（列表）、`02-pause-confirm.png`（暂停二次确认）、`03-after-pause.png`（暂停后）、`04-resume-deleted.png`（恢复已删除证书的确认）；`result.json` 中 `okDisabledInitially=true`、`okEnabledAfter=true`、`afterPause=管理员已暂停`

## 遗留问题（未改契约，需架构师定）

1. **对“未暂停但已设置证书”的用户调 resume**：契约没写。后端（be607b3）实现为 204、不变但写审计；前端只在 `paused_by_admin` 行显示“恢复”，不会主动发这种请求。请在契约补一句。
2. **列表筛选与排序**：契约没定义 `GET /admin/data-licences` 的筛选参数和排序。前端按后端实现（用户 `created_at desc, id desc`）展示，筛选只在已加载的行上做并写明。用户多时建议加 `?status=`（可多值）与 `?q=`（用户名）。
3. **暂停理由与审计不可见**：契约没有接口返回当前暂停的理由、操作人、时间，管理端只能看到状态。如需要，请加字段（如 `admin_pause: {reason, by, at} | null`）或审计查询接口。
4. **冷却期**：T-B03e 的“删除后重提不跳过冷却”只影响用户侧 PUT，管理端接口看不到冷却状态；前端未展示。如管理员需要知道，请加字段。
5. **暂停对用户的告知**：暂停 / 恢复后是否给用户发通知（`notification_kind=data_licence`）契约未写；前端未处理。

## 需要谁做什么

- 架构师：评审 d26e1d3；处理上面遗留 1–5（至少 1、2 补一句）。T-A09-frontend 遗留 4、5、6 可关闭。
- 运维：推送 d26e1d3（本地未 push）。
- 后端：无须改动；如契约补 1–4，按契约实现。
