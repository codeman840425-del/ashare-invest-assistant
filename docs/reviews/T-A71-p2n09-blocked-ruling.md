# T-A71 裁定：P2N-09 四个 blocked 用例（C12、C13、C14、C21）

> 架构师，2026-11-09（America/Denver）。输入：team 报告 T-R32（strat/T-R32 头 a9e260c，已快进进 integ/teamb-p2）。只读核对契约、plan 与现有代码，不改 docs/strategies（属研究员）。
> 行号按 integ/teamb-p2 @ a9e260c。

## 总裁定

四个用例**都可以解除阻塞，改成 ready 离线用例**，总数仍为 26，counts 改为 ready 26 / blocked 0。原来的阻塞理由，一部分是误引契约，一部分是把「后端生产实现」混进了「解释链金标准」。真实环境的验证另列为后端和测试的验收项，不计入 26 例，也不允许冒充离线通过。

## 依据

- 契约 §7.11.4 T-A36 第 3 点（docs/api-contract.md:1279）：`llm_call_id` 只对管理员有意义；仅当管理员且已有 `/admin/llm/usage` 页时显示链接 `/admin/llm/usage?call_id={id}`，否则管理员只读显示 id；非管理员不显示。这是**纯渲染投影规则**，输入只有角色、页面是否存在和 id 三项，可以离线判定。
- 草稿 §5 把 C12–C14 的阻塞理由写成「管理员会话 `origin=password_login`（T-A18/T-A20）」（docs/strategies/p2n09_golden_draft.md:249），这是**误引**。T-A20 的可信交互会话只约束 G7 晋级决定（docs/api-contract.md:953），与查看 llm_call_id 或 usage 无关。
- 前端已经实现并测试了这条规则：src/frontend/src/lib/explanations.ts:13-16（`hasAdminLlmUsagePage()` 目前恒为 false，深链函数按角色、页面和 id 三者判定），src/frontend/src/components/ExplanationView.tsx:13-14、39，src/frontend/src/pages/p2n05-ai.test.tsx:186-194。
- 缓存：契约只规定「解释在不可变正文提交之前生成或回退，提交后不异步改正文」，以及回退不影响规则结论（docs/api-contract.md:1283）；`llm_call_id` 在「有调用记录」时非空（docs/api-contract.md:1278）。缓存的粒度在 plan 里：同一 (code, method_version, snapshot) 的个股事实解读**只在同一证书内**复用，涉及个人持仓的段落按用户生成（docs/plan.md:164）。草稿把缓存键写成 `(user, 对象哈希, prompt_version)`（docs/strategies/p2n09_golden_draft.md:248），与 plan 不一致。
- 后端现状：解释目前一律是模板，`llm_call_id=None`（src/backend/app/suggestions/aggregate.py:148，src/backend/app/reports/service.py:360）。没有 LLM 网关缓存，也没有 `/admin/llm/usage` 路由。所以「生产行为」现在根本无从实测，继续 blocked 也等不来真实环境。

## 逐例裁定

| 例 | 裁定 | 解除阻塞的口径 | 谁做什么 | 验收 |
|---|---|---|---|---|
| C12 非管理员不显示 id | **改 ready（离线投影）** | 输入 `viewer_role=user`、`usage_page_available` 取任意值、`llm_call_id` 非空，期望渲染投影里**没有** id，也没有链接。草稿 §3.3 原有的判定（docs/strategies/p2n09_golden_draft.md:141-144）不变 | 研究员：在 golden JSON（docs/strategies/golden/P2N-09_golden.json:457）去掉 `block_reason`，补上 expected；在 check_P2N-09.py 增加 `auth_leak` 分支，并去掉 blocked 短路的依赖（docs/strategies/golden/check_P2N-09.py:47-49） | 正例 accepted；篡改成「显示 id」时 rejected，finding 为 `llm_call_id_leak` |
| C13 管理员无 usage 页时只读 | **改 ready（离线投影）** | 输入 `admin`、`usage_page_available=false`，期望显示 id 纯文本、没有 href | 研究员：同上（json:478），增加 `auth_plain` 分支 | 正例 accepted；篡改成「生成链接」时 rejected，finding 为 `link_without_usage_page` |
| C14 管理员有 usage 页时显示深链 | **改 ready（离线投影）** | 输入 `admin`、`usage_page_available=true`，期望 href 精确等于 `/admin/llm/usage?call_id=` 加 URL 编码后的 id；自拼或错误路由都判 rejected | 研究员：同上（json:499），增加 `auth_link` 分支，变异集至少要有「错路由」和「未编码」两种 | 正例 accepted；两个变异都 rejected |
| C21 缓存命中不重复调用 | **改 ready（离线不变量）**，真实缓存另列 | 只判链路不变量：`cache_hit=true` 且 `invoked=false` 时，explanation 与来源记录逐字节相等，`llm_call_id` 等于来源记录的原值（溯源到产生这段文字的那次调用），不得出现新 id。缓存键不写进 golden；如果要写，以 plan.md:164 为准（同证书、code、method_version、snapshot，加 prompt_version），不按 user 写 | 研究员：改 json:694 和 checker 的 `cache` 分支，修正草稿:248 的键。**后端**：将来实现 LLM 网关缓存时，在 selfcheck 里断言缓存命中不新增 `llm_calls` 行、不跨证书复用 | 正例 accepted；篡改成新 id 时 rejected，finding 为 `duplicate_llm_call`；篡改正文时 rejected |

## 另列的真实环境项（不计入 26 例，也不是 C12–C21 的阻塞条件）

1. 后端：实现 `GET /admin/llm/usage?call_id=` 🛡（docs/api-contract.md:1279）。非管理员 403；返回内容不含个人信息和 key。实现之后，前端把 `hasAdminLlmUsagePage()` 改为 true 并更新 p2n05-ai 测试。在此之前保持 false，也就是 C13 的形态。
2. 后端和测试：LLM 网关缓存上线时，按 C21 的不变量补真实库用例（合成数据，不真实外呼）。
3. 测试：研究员改完后，在 docs/strategies/golden 下运行 `check_P2N-09.py`。

## 总体验收

- `check_P2N-09.py` 输出 ready 26/26、blocked 0；26 个 ready 用例的篡改集全部被拒，C12、C13、C14、C21 每例至少 1 个变异。
- 全部 `fictitious=true`；不新增 API 字段、枚举或拒绝码；免责文本 sha256 不变。
- 草稿 §5 表改为：C12–C14 不再列出，C21 只保留「真实缓存落库」作为后端项，并删掉对 T-A20 的误引。
