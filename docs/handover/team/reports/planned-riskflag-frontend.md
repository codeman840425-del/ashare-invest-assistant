# planned 状态显示 + 风险标记文案（契约 #29）（前端）

- 依据：契约 v0.2.9 §3 `security_risk_flag`（#29，docs 66f0c79 / 1d02980 原文）、§6.0 / §7.7A `research_candidate_status`
- 提交：`e2aacd0`（功能 + 测试，6 文件，仅 src/frontend/）；`c4329bc`（T-F12 刷新用例偶发超时的测试跟进，见下）
- 干净检出：c4329bc 上 rc=0（39 文件 / 585 测试；eslint、typecheck、audit（high 级 0；有 1 个 moderate）、build、check:dist、build:mock 全过）
- 截图：reports/planned-riskflag-frontend/01-risk_flag.png（个股页“退市风险警示”Tag）、02-planned-list.png（研究候选列表“已计划”）；1440×900 暗色，console error 0，外部请求 0

## 已做
- 风险标记文案（i18n `SECURITY_RISK_FLAG`）：`star_st` → **退市风险警示**，`delisting` → **退市整理**，`st` → 其他风险警示（按 #29 原文“st = 其他风险警示（ST）”）；悬停说明带简称（ST / *ST）和“证券简称带‘退’的退市整理标记”；旧文案“退市风险”删除。用在个股页头 Tag、搜索下拉、研究候选 mock 反证
- `delisting` 标记与上市状态 `listing_status=delisting_period`（“退市整理期”）分开显示，按契约不合并
- planned：列表 Tag、状态筛选、详情页“已计划”提示、终态不出新建版本入口；`plan_ids` 为空时不出计划链接（契约 #30 ④：本版 `plan_ids=[]`）
- Mock（均标示例）：演示材料 002001.SZ 带 `star_st`；管理员示例账户下一条 planned 研究候选（契约写明本版实际不会出现 planned、前端仍要能显示；放在 admin 账户下，不影响 demo_user 数据）
- 测试 pages/planned-riskflag.test.tsx（8 例）：文案 = 契约原文且覆盖全部枚举；mock 搜索/主数据一致；个股页 Tag 与悬停；无标记不出 Tag；planned 列表/筛选/终态 409 `allowed=[]`；详情页显示与无链接；他人 404

## 附带修复
- `c4329bc`：t-f12“手动刷新→409”用例在整套并行跑时偶发 1 秒超时（第一次干净检出发现），改为本文件异步等待 5 秒并等按钮可用后再点。同时发现本地干净检出脚本用 `grep` 过滤 vitest 输出时没有 `pipefail`，测试失败也报 rc=0；已改脚本（`set -o pipefail`）并重跑。之前 7b47ace、05d8a16 的干净检出日志里没有失败用例，结论不变

## 缺失的契约项
- 无（#29 三个值的含义已写全）。可选确认：`st` 是否在界面上显示全称“其他风险警示”，还是只显示简称“ST”（目前显示全称，简称放悬停）

## 需要谁做什么
- 编排者：验收；如需改为只显示简称，说一声即可
