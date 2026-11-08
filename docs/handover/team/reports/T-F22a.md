# T-F22a 前端评审修复报告（含 T-O09 前端根因）

- 评审：/workspace/team/reports/review-T-F02b-F05-F22-F03.md
- 提交（本地 main，未推送）：
  - `527b65e` fix(frontend): T-F22a 评审修复（B1、M1、M2、m1–m19）
  - `39c6d80` test(frontend): 契约版本用例不再要求与 docs 当前版本逐字相等（fa6d55d 升 v0.2.7 后干净检出 vitest 失败，见下文）
- 8405877（T-F08 /today）仍在历史中（`git merge-base --is-ancestor 8405877 HEAD` 为真）。
- 只改 src/frontend/；未改任何 .gitignore。

## T-O09 根因结论：是 B1
`src/frontend/src/mocks/licence.ts` 命中了根目录 .gitignore 旧规则 `licence.*`，从未进入版本库；本地能跑，干净检出（CI）里
`mocks/session.ts`、`mocks/accountHandlers.ts`、`pages/t-f22.test.tsx` 引用的模块不存在 → typecheck / vitest / build 全部失败。
- 前端修复：改名为 `mocks/licenceStore.ts`，同步全部引用；`git check-ignore -v` 对新文件无输出（exit 1）。
- 守卫：`src/test/tracked-sources.test.ts` 遍历 src/、scripts/，用 `git check-ignore --no-index --stdin` 断言无被忽略的源文件。
- 已排查 src/frontend 下其它被忽略但被引用的源文件：无（运维新增的 `scripts/ci/check_ignored_sources.py --worktree`：错误 0）。
- 运维在此期间提交了 713a276（T-O09a 收窄 .gitignore、加 ignored-sources CI 和 clean_check.sh），与本修复互不冲突、互为双保险。
- 另外发现：8405877 里的 `scripts/screenshot-tf08.mjs` 有一个 eslint 错误（`/* global document */` 未使用），CI lint 也会失败；本次已修复。

## 干净检出验证（CI 方式）
`git worktree add --detach /tmp/wt-verify HEAD(39c6d80)`，Node 22.23.4 / pnpm 10.34.6，在 src/frontend：
`pnpm install --frozen-lockfile` ✓ · `eslint . --max-warnings=0` ✓ · `pnpm run typecheck`（app/node/test）✓ · `vitest run` 19 文件 299 例全过 ✓ ·
`pnpm audit --audit-level high` ✓ · `build` + `check:dist` ✓ · `build:mock` + `check-dist dist-mock --expect-present` ✓ · 仓库根 `check_ignored_sources.py` 错误 0 ✓。

注意：架构师 06:38 提交 fa6d55d 把契约升到 v0.2.7，前端旧用例断言 `版本：**v0.2.6**`，导致干净检出 1 例失败。
39c6d80 改为“CONTRACT_VERSION 在契约变更记录中存在且不高于当前版本”。对齐 v0.2.7 的工作在下一个提交（T-A08-frontend）。

## 逐条对应
| 项 | 修复 | 测试（src/pages/t-f22a.test.tsx 等） |
|---|---|---|
| B1 | 见上 | tracked-sources.test.ts |
| M1 | 证书 PUT/PATCH/DELETE/test 成功后 `syncMeLicence` 写回 /me 缓存；`useMe` 每 60s 轮询 | 提交 X-INVALID 证书后横幅不刷新页面即变为 invalid |
| M2 | 新增 `KeyTip`（tabIndex=0、role=button、Enter/Space 开合、Esc/失焦关闭、aria-expanded、aria-describedby 指向全文）；`DataStatusTag` 改用 KeyTip；新增 `GapNote` 在行情、图表、四个页签、市场概览、板块资金直接显示缺数原因，证书原因附“去设置数据证书”链接；mock 按本人证书状态降级（行情/日周K/个股数据 stale，分时与板块 unavailable 并清空 items），gap 为 `data_licence_unavailable` | 个股页各处、市场页、键盘开合、证书可用时不出现 |
| m1 | 任一证书操作开始时 reset 全部 mutation，旧错误不残留 | 失败后再次成功，错误框消失 |
| m2 | 输入框 autoComplete=off、data-1p/lp/bw-ignore，增加“不会保存在浏览器”说明 | 属性与说明 |
| m3 | DATA_LICENCE_IN_USE/NOT_SET/UNAVAILABLE 中文文案，UNAVAILABLE 带状态；RATE_LIMITED 带等待时长；ErrorBox 对证书错误给设置页链接 | errorText 单测 |
| m4 | mock：PUT 10 次/时、/test 5 次/时 → 429 + Retry-After + retry_after_s；/test 采集暂停 → 503 INGEST_PAUSED | 429、503 与页面文案 |
| m5 | 开关 aria-label 固定为模板名，风险说明经 aria-describedby 关联 | 属性断言 |
| m6 | 已有 proposed 实例时启用走 `/confirm`，不重复 POST | 只调 confirm、无 POST |
| m7 | 无账户 → 提示并禁用开关；账户加载失败 → ErrorBox | 两例 |
| m8 | mock 先判 409 STRATEGY_VERSION_NOT_RUNNABLE `{lifecycle}`；HORIZON_MISMATCH details 带 strategy_key；页面对不可运行版本禁用开关并说明 | 409 结构、禁用 |
| m9 | `fetchAllPages` 跟随 next_cursor（每页 200、最多 10 页），超限 truncated 并提示 | 翻页/截断/不截断 |
| m10 | 周期封顶与提示用 KeyTip，可聚焦、Enter 打开 | 键盘 |
| m11 | 周线说明改为“周线日期取该周最后交易日”；空图文案按分时/日K/周K区分并附缺数原因 | 文案 |
| m12 | 日K 尚无当日 bar 时昨收取 1m 响应顶层 pre_close（仅同一交易日） | 去掉当日日K后昨收=1m pre_close |
| m13 | 路由代码 trim+大写，非规范写法 replace 到规范 URL（保留 query）；搜索词 trim 后进 queryKey 与参数 | 跳转与参数 |
| m14 | 未知 account_id 提示并回落第一个账户；导入链接 encodeURIComponent | 回落、不以未知 id 请求 |
| m15 | 页脚去掉 role=note，保留 contentinfo 地标 | 角色断言 |
| m16 | mock bars：缺 freq → 400；limit 默认 500、1–2000；before 过滤；next_before | 翻页 |
| m17 | 切换周期保留旧图（placeholderData 仅同一代码），aria-busy 标识加载 | 切换中旧图仍在 |
| m18 | `droppedBars` 统计落不到分钟轴的 1m bar，开发态 console.warn，图上 data-dropped | 单测 |
| m19 | 市值 Number 乘法保留，注释说明精度足够（误差远小于 0.01 亿） | — |

## 截图（build:mock + vite preview，仅 <host>；外部请求 0、控制台错误 0）
- /workspace/team/reports/T-F22a/01-licence-banner-auto.png（M1 横幅自动变为无效）
- /workspace/team/reports/T-F22a/02-stock-gap-notes.png（M2 个股页缺数原因 + 键盘打开数据状态说明）
- /workspace/team/reports/T-F22a/03-market-gap-notes.png
- 脚本：src/frontend/scripts/screenshot-tf22a.mjs；result.json 同目录

## 扫描
secret_scan files/staged 阻断 0 警告 0；gitleaks dir/staged（仓库配置 + 默认规则）均 no leaks；暂存只含 src/frontend/。

## 需要谁做什么
- 运维：推送时把 527b65e、39c6d80 一起推；CI 已有 ignored-sources 与 clean_check.sh，无需再改。
- 无需后端或文档改动。
- tooltip 里的 gap key（如 `quote.600000.SH`）是契约原样字段，若产品觉得太技术化，可以后再隐藏，不阻断。
