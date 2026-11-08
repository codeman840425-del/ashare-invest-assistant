# 评审 5c282da（前端：研究候选页面 T-F23，契约 §7.7A）

- 评审人：架构师；写于 2026-11-02 09:47 北京时间；只读评审。
- 依据：契约 v0.2.9 §6.0、§7.7A（第 943–978 行）、§9 v0.2.9 验收要点；T-A11；reports/T-F23.md。

## 结论：**通过**（无 B、无 M；4 个 m）

## 逐项核对（T-A11）
| 项 | 结果 | 位置 |
|---|---|---|
| 只有 manual / from_stock / suggestion 三种入口 | 符合：`CandidateCreateOrigin` 排除 strategy_screen；建议详情 → suggestion，个股页与候选信号详情 → from_stock，研究候选页 → manual；mock 对 strategy_screen 返回 400 not_supported。列表 origin 筛选含 strategy_screen 属 GET 筛选，可以 | api/candidateTypes.ts；features/research/AddToResearch.tsx；pages/SuggestionDetailPage.tsx、stock/StockPage.tsx、signals/CandidateSignalDetailPage.tsx；mocks/candidateHandlers.ts:239–240 |
| ⚖ 免责声明 | 列表与详情都有 CardDisclaimer | pages/research/CandidatesPage.tsx:105、CandidateDetailPage.tsx:69 |
| 反证为空时固定文字 | “系统未列出反证，不代表没有风险”，与契约一致 | features/research/VersionView.tsx:63–68；i18n/candidateLabels.ts:16 |
| 409 CONFLICT 显示 existing_id 并跳转 | 符合：错误区给“查看已有候选”链接到 `/candidates/{existing_id}`（点击跳转，不自动跳转，可接受）；入口组件在已有 researching/watching 候选时直接给链接 | features/research/candidateForm.tsx:64–93；AddToResearch.tsx |
| 历史版本只读 | Drawer 只读展示 | CandidateDetailPage.tsx:172–174 |
| 终态不能建新版本 | dropped/planned 时不渲染 NewVersionPanel；409 `allowed:[]` 有专门文案 | CandidateDetailPage.tsx:65；candidateForm.tsx:82–88 |
| 决定理由 1–200 | `required + whitespace`，trim 后 >200 拦截；mock 同样 trim 后校验 | CandidateDetailPage.tsx:131–142；mocks/candidateHandlers.ts:310–315 |
| 列表默认不显示 dropped | `DEFAULT_CANDIDATE_STATUS` 不含 dropped；mock 默认 researching,watching,planned | api/candidateQueries.ts；mocks/candidateHandlers.ts:209 |
| 写操作后刷新 | 成功后 invalidate `['candidates']`（列表、详情、版本、入口反查同前缀）；带 Idempotency-Key | api/candidateQueries.ts |
| VERSION_CONFLICT | 显示 current_version_no，提供重新加载 | candidateForm.tsx |
| mock 与契约一致 | 校验顺序（请求体→证券→来源建议→重复；新版本：请求体→本人→终态→乐观锁）、ETF/指数 400、他人候选 404、幂等重放与 IDEMPOTENCY_CONFLICT 均符合 | mocks/candidateHandlers.ts:205–332 |

## 问题
- B：无。M：无。
- m1 `from in RESEARCH_STATUS` 走原型链，与 N1 同类（`from="toString"` 会读到原型属性）。改 `Object.hasOwn(RESEARCH_STATUS, from)`（features/research/candidateForm.tsx:86）。
- m2 终态 409 或 VERSION_CONFLICT 后，页面上的状态标签仍是旧值；终态 409 时应 invalidate `['candidates']`，让页面变成终态只读（candidateForm.tsx:82–88；CandidateDetailPage.tsx:97 onError）。
- m3 决定理由 `maxLength={220}` 与 1–200 规则不一致（允许多打 20 个字再报错）。含首尾空白时的余量可以理解，但 showCount 显示 220 上限会误导；建议 `maxLength={200}` 并在输入时 trim，或 showCount 用 trim 后长度（CandidateDetailPage.tsx:140）。
- m4 mock 没有对 `/candidates*` 的 PUT/PATCH/DELETE 返回 405（契约 §7.7A“没有删除接口”）。测试环境 onUnhandledRequest 会报错，问题不大；补上可与后端对齐（mocks/candidateHandlers.ts）。
- T-F23.md 的待定 1–7 已在本轮裁定（frontend-pending-rulings.md 第 3B 节），其中 3（fit.hints 恒为 []）只是 mock 简化，不影响前端。

## 测试（干净导出，串行，跑完已删）
| 项 | 结果 |
|---|---|
| typecheck | rc=0 |
| lint | rc=0 |
| vitest | 33 个文件通过 + 1 跳过；510 通过 + 1 跳过（共 511） |

## 谁需要做什么
- 前端：m1–m4。
- 后端（T-B10，已提交 83a031c）：按 §7.7A 与本轮裁定 3B 联调；405 行为与 mock 对齐。
