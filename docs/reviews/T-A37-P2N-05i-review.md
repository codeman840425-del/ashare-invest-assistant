# T-A37｜P2N-05i 前端评审

## 范围与结论
- 目标提交：`0c2083485b171b0b29d56eccbaacb00aa7753de8`（本机 main，未推送）；行号基准：`3b36b74d7bf9187a00816008f3eca5a19c3f137a`。相对 78cd872，受评前端文件无提交差异；不评价其他人的未提交 WIP。
- 依据：契约 §7.11.4 原 explanation 追加字段与 T-A36 第1–6点（78cd872）；交付说明 `/workspace/team/reports/P2N-05i.md`。
- **结论：原契约 mock 展示未发现新增确定缺陷；按 T-A36 更新后再验收。阻断0、重要3、建议0。** 下列 I1–I3 全部属于“按新裁定需改”，不是追认 0c20834 提交时已违反尚未形成的规则。
- 本次仅写本评审文档，不写 team/reports/T-A37.md、不更新状态、不联系其他 agent、不修改实现或夹具。

## 重要｜按新裁定需改
### I1 逐股/分歧仍复用顶层，须改为读取本项 explanation（前端）
- 位置：`src/frontend/src/pages/DailyReportPage.tsx:133,218`；`src/frontend/src/pages/SuggestionDetailPage.tsx:274`；`src/frontend/src/api/types.ts:246–250,288–306`；`src/frontend/src/mocks/explanationFixtures.ts:148–156`。
- 现状：每股折叠区使用 `r.explanation`，每个分歧使用 `sg.explanation`，虽明确标“非专属”，但不会读取后端新提供的本项解释；类型缺 `DailyReportStock.explanation` 与 `Divergence.explanation`。日报提示仍称不存在独立字段，已不符合新契约。
- 按 T-A36 第1点：读取 `stocks[].explanation` / `divergence[].explanation`；null 或缺键时该位置不显示任何解释区，不得以顶层解释回填，也不得按证据筛选顶层段落猜绑定。顶层整体解释仍可在自己的整体区保留。
- 修改：类型支持 `explanation?: Explanation | null` 兼容旧档；MSW 明确提供独立逐股/分歧解释、null 与旧缺键三种场景。本项引用须遵守逐股证券前缀、分歧 dimensions 归属，由后端冻结并校验，前端不自行生成解释/归属。
- 回归：修改 `p2n05-ai.test.tsx:68–94` 中“展开非专属整体解释”及 stocks 必须缺 explanation 的旧断言；用不同正文区分顶层、两只股票、两项分歧，验证只显示本项、空值不显示、互不串引用，规则 UI 与导航保持不变。

### I2 缺 fallback_reason 类型/五值展示，夹具缺新记录必需键（前端）
- 位置：`src/frontend/src/components/ExplanationView.tsx:16–22`；`src/frontend/src/api/types.ts:252–259`；`src/frontend/src/mocks/explanationFixtures.ts:127–133`；`src/frontend/src/mocks/suggestionHandlers.ts:79`。
- 现状：所有 fallback 只显示通用“模型未启用或失败…接口未提供原因”；Explanation 没有 fallback_reason；新生成 success/disabled/failure 与手动刷新夹具均未携带它，无法检验后端五类结果。旧 template 且 validation_status 缺失时也没有明确“模板兜底”状态文案。
- 按 T-A36 第2点：支持 `fallback_reason?: 'not_enabled' | 'budget_exceeded' | 'timeout' | 'provider_error' | 'validation_failed' | null`；passed 必为 null，fallback 新记录必非空。分别展示未启用/未配置、预算超限、超时、上游失败、验证拒绝；只读服务端值，不根据 source/prompt_version/调用id猜具体原因。
- 旧档缺键时回退原因位置只显示“模板兜底”（对 source=template 的旧记录亦然），不猜未启用/失败；不把 legacy_llm 强行改标为 fallback。
- 修改：补类型与枚举映射，更新 MSW 新记录及刷新结果；not_enabled/budget_exceeded 的 llm_call_id=null，其余有调用记录可非空；旧档继续真实缺键，不补造新元数据，不自造替代字段。
- 回归：五值逐个命中文案、passed+null、旧档缺键、非管理员但错误调用记录存在仍隐藏（见I3）；paragraphs/text、引用解析与规则字段不变。

### I3 llm_call_id 无角色限制，须仅管理员显示（前端）
- 位置：`src/frontend/src/components/ExplanationView.tsx:7–9,34`；调用点 `src/frontend/src/pages/SuggestionDetailPage.tsx:304`、`src/frontend/src/pages/DailyReportPage.tsx:133,221`。
- 现状：组件不接收或检查当前用户角色，任意 explanation.llm_call_id 非空即显示，包含 template/fallback 调用；现有纯合成夹具 id 都为空，现有通过测试没有覆盖此新角色要求。
- 按 T-A36 第3点：非管理员完全不显示调用id；管理员在已有 `/admin/llm/usage` 页面时才显示 `/admin/llm/usage?call_id={id}` 链接，否则只读显示id。当前前端 src 搜索未发现该页面/路由，因此应先采用“管理员只读id”，不可自造可点击404链接；后端GET接口存在不等于前端页面存在。
- 修改：使用既有可信当前用户上下文统一门控所有 ExplanationView，加载中/角色未知按非管理员处理。未来页面接入后再启用编码后的 call_id 深链；不要以是否有id或source=llm代替管理员判断。
- 回归：普通用户、管理员、角色未知三组，配非空id；普通/未知 DOM 不含id；无页面时管理员只有文本、有页面时才有正确链接。覆盖建议、日报整体及新增本项解释调用点。

## 已核对、无新增问题
- 原三新增键为可选，符合旧档缺 paragraphs/prompt_version/validation_status 时退回 text 的兼容要求；`ExplanationView:12` 优先非空段落、否则旧 text，不补造出处。
- `ExplanationView:16–23` 在 source=template 时标“模板解释（非 AI 生成）”，不展示“AI 中文解释”；来源/验证状态矛盾时改标待确认而非假装通过。
- React 文本节点渲染正文、prompt_version 与证据值，无 dangerouslySetInnerHTML；`ExplanationView:24–39` 不解析 HTML。引用仅在传入 evidence 中查找，缺失时显示缺失、不向其他对象借证据；每实例 useId 独立锚点。
- 解释组件不接收 action/score/confidence，页面继续从规则结构渲染动作/分值/置信度；MSW 包装只替换 explanation/追加合成 evidence，不改规则字段。规则与解释分区，解释点击阻止卡片导航。
- 固定免责仍由两页既有 CardDisclaimer 独立渲染；本提交未改 RiskDisclosure.tsx。文本为：“本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。”，不经解释模型、不拼入 paragraphs。
- T-A36 第4–6点是 P2N-09 后端解释生成/守卫职责：数字精度、动作词无白名单、否定/引用禁词无例外。前端应显示服务端已冻结且守卫通过/模板回退的结果，不在前端另做数字推导、关键词替换、动作转述或免责声明生成。当前纯合成文案未见新增数值/动作转述/承诺；不能据 mock 测试声称真实模型守卫已验收。
- 本提交未自造逐股或分歧响应键；I1/I2 是新裁定带来的合法加键需求，不应继续用“不自造键”为由拒绝补齐明确契约字段。真实后端与权限过滤仍需 P2N-09 联调。

## 验证与边界
- 本次运行：`./node_modules/.bin/vitest run src/pages/p2n05-ai.test.tsx`（src/frontend），**1文件29测试通过**；MSW/内存环境，不需要真实外部服务，未启动开发服务器。
- 测试反映旧 mock 口径，尤其非专属整体复用断言；通过不代表 T-A36 新绑定/回退/角色口径通过，修复后必须更新并重跑对应断言。
- 未跑全量测试、coverage、build或tsc；未调用模型/DeepSeek、麦蕊或其他真实外部服务，未读取密钥或真实用户数据。
- 提交前仅对本文件执行 files 模式 secret_scan（阻断必须0）及 `git diff --check -- docs`，本地单路径提交，不 push、不带他人暂存。

DeepSeek：未用，原因 评审结论禁止外包。
申请新任务：前端按T-A36修正I1–I3后定点复审，并与P2N-09冻结解释接口联调。
