# 评审 b23401a 修复（前端，提交 1/3）

- 提交：`d0c7ccb`（只本地，未 push）。父提交 `bbf58a0`（他人：T-B46 后端）。
- 范围：只含 `src/frontend/`（`git show --name-only` 核对，30 个文件，非前端 0 个）。v0.2.9 的进行中改动在动手前已用 `git stash`（stash<at>{0} “v029-sync-wip (frontend only)”）隔开，未混入本提交。
- 依据：reports/review-b23401a.md（第七节 N1–N8、第八节）、reports/review-d26e1d3.md（m1–m3）。

## 一、逐条处理

| 条目 | 处理 | 位置 | 测试 |
|---|---|---|---|
| d26e1d3 m1 管理端证书列表过期显示“剩 -N 天” | b23401a 中已改为共用 `expiryLeftText`（已过期 / 今天到期 / 剩 N 天），本次补管理端列表测试 | `i18n/licenceLabels.ts`、`pages/admin/AdminDataLicencesPage.tsx` | review-b23401a.test.tsx “已过期…今天到期…不出现剩 -N 天” |
| d26e1d3 m2 跳转目标行在前 50 行之外看不到高亮 | 契约的管理端证书列表没有按 user 过滤的参数（不猜），按契约已有的游标分页自动 `fetchNextPage` 直到找到目标行，找到后高亮并滚动到该行；最多续加载 40 页，超过或全部加载完仍找不到给出提示（`lic-focus-missing`），加载中显示 `lic-focus-searching`，目标行已加载但被本地筛选隐藏时提示（`lic-focus-hidden`） | `AdminDataLicencesPage.tsx` | 75 行中定位第 61 行（请求游标 null→50，命中后停止、已滚动）；全部加载完找不到→提示且不再请求；被筛选隐藏→提示 |
| d26e1d3 m3 mock 理由长度未去首尾空白 | 先 `trim()` 再按 1–200 字校验，纯空白视为未填（400 required） | `mocks/accountHandlers.ts` | 纯空白→400 `{field:'reason',issue:'required'}`；两端加空格的 200 字→204；201 字→400 |
| N1 原型链键命中 | 改用 `Object.hasOwn(SIGNAL_STATE/PLAN_DRAFT_STATUS, from)` | `lib/stateTransition.ts` | from=toString/constructor/__proto__/hasOwnProperty 均回落 null |
| N2 span 上的 aria-label | chip 加 `role="button"` | `components/EvidenceChips.tsx` | t-f13 aria 用例 |
| N3 空格滚动页面 | Enter/空格均 `preventDefault` + `stopPropagation`；点击也不冒泡 | 同上 | t-f13：keyDown 返回 false、点击 chip 不跳转 |
| N4 可交互元素嵌套 | 卡片去掉 role=link/tabIndex（鼠标点卡片仍可进入）；键盘与读屏用标题处的真实 `<Link>`；chip 不在链接内 | `pages/DailyReportPage.tsx` | t-f13 “逐股卡片”“aria” 用例 |
| N5 名称丢了去向 | 链接名 = “名称 代码：查看候选信号卡”（隐藏说明节点），卡片 `aria-labelledby` 指向标题 | 同上 | t-f13 |
| N6 loadOlder 等待后无条件跳转 | await 后检查组件仍挂载且地址未变（地址用 effect 写入 ref） | `DailyReportPage.tsx` DateSwitcher | t-f13 新用例：先缓存 10-20，回最新一期点“上一期”（下一页请求被挂起），再切到 10-20，放行后仍停在 10-20。已验证去掉该检查时此用例失败（被拉到 10-29） |
| N7 blocked 的 allowed | `signalAllowed`（实际在 `mocks/planHandlers.ts`，评审写的是 signalHandlers）blocked → `['released','dismissed']` | `mocks/planHandlers.ts` | 对 blocked 信号 POST /plan-drafts → 409 allowed=[released, dismissed] |
| N8 全局超时放宽 | 已还原：删除 setup.ts 的 `asyncUtilTimeout: 5000` 和 vite.config.ts 的 `testTimeout: 20_000`。还原后干净检出连续多次运行出现偶发超时（每 3 次约 1 次，位置不固定：t-f22/t-a09/t-f17 首个渲染用例），原因是懒加载页面模块的冷转译落在 findBy 等待窗口里。处理：新增 `src/test/preloadRoutes.ts`，渲染路由的 21 个测试文件在 `beforeAll` 里预加载页面模块（钩子单独 30 s）；仅 t-f17 首个 AG Grid 渲染的一处 `findBy` 单独设 5 s。全局保持默认 | `test/setup.ts`、`vite.config.ts`、`test/preloadRoutes.ts`、各测试文件 | 见第二节 |

## 二、测试结果（分开报告）

**带 .git 的工作区**（/workspace/ashare-invest-assistant/src/frontend）：
- `pnpm run typecheck` 通过；`eslint . --max-warnings=0` 0 问题；`vitest run` 32 个文件 467 个用例全部通过（默认超时）。

**干净检出**（`git worktree add --detach` 于 d0c7ccb，`pnpm install --frozen-lockfile`）：
- 修复 N8 前（仅还原超时）：第一次 cleanci 3 个失败，另 4 次中 1 次失败（均为等待超时）。
- 加入预加载后：独立工作区连续 6 次 `vitest run` 全部 467 通过；最终 `/tmp/cleanci.sh`：ignored-sources 错误 0 / 告警 4（既有）；eslint 0；typecheck 通过；vitest 467/467；`pnpm audit --audit-level high` 1 moderate（既有，未达 high）；build + check:dist 0 命中；dist-mock 反向自检有效；rc=0。

**提交前扫描**（`rm -rf dist dist-mock` 后）：secret_scan files 202 个文件 阻断 0 警告 0；gitleaks（仓库配置 / 默认配置）no leaks；暂存区 gitleaks no leaks；secret_scan staged 阻断 0 警告 0；禁用词与 11 位数字 0 命中；`git diff --cached --stat` 仅 src/frontend/。

## 三、遗留 / 待定

- 问题 72（沿用）：契约的管理端证书列表没有按 user 查询的参数。目前用游标续加载定位，最多 40 页（2000 位用户）；用户量更大时请契约补 `?user_id=` 过滤，前端届时改为直接查询。
- N8 的预加载是测试侧改动，不影响产品代码；如评审认为需要，也可以只在 CI 用环境变量调高（未采用）。

## 四、他人的改动（未触碰、未 add）

- 新增他人提交：`bbf58a0` feat(backend) T-B46（作者 codeman840425-del，2026-11-02 08:44 北京时间），未涉及 src/frontend；此前的 `483fe2c`、`439746e` 也是他人提交。
- 工作区他人未提交改动（截至 2026-11-02 09:03 北京时间）：已修改 src/backend/app/api/v1/__init__.py、api/v1/admin.py、auth/deps.py、auth/sessions.py；未跟踪 src/backend/app/api/v1/horizon.py、licences/ingest_status.py、strategy/horizon/（__init__、classifier、inputs）。另有 deploy/、docs/、.github/ 等未跟踪项。

## 五、需要谁做什么

| 谁 | 做什么 |
|---|---|
| 评审 | 复核 d0c7ccb；重点看 N8 的处理方式（全局默认 + beforeAll 预加载 + 一处单独超时）和 m2 的续加载上限 |
| 架构师/契约 | 问题 72：是否给管理端证书列表加按用户过滤参数 |

## 截图（1440×900 深色，示例数据）

- `review-b23401a-fixes/01-admin-licences-expiry.png`：管理端证书列表的到期显示（m1）。“已过期”状态只有测试覆盖，没有单独截图。

## 收尾补记（2026-11-02 09:47 北京时间）

- d0c7ccb 之后的前端提交：7a3e9cb（v0.2.9）、5c282da（T-F23）、0e31218（CSRF）。这些提交都没有回退本次修复，0e31218 的干净检出测试结果为 531/531。
