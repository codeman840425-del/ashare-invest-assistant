# 评审 d3be426（T-B50 部分：/meta/enums v0.2.9）

- 评审人：项目架构师；时间：2026-11-01 20:50（America/Denver，UTC-7）
- 方式：只读。干净导出后 `uv sync --frozen`；在临时容器（只绑 <host>）里跑 dump_meta_enums、check_contract --meta-json、check_code_namespaces --meta-json，并起应用做了几个接口探测；没有推送，没有调用麦蕊。

## 结论：可以推送

contract 任务从本提交起转绿。这是 34d475d 之后第一个能让 contract 任务变绿的后端提交，建议和前面的提交一起连推到这里。

## 1. 实测
| 项 | 结果 |
|---|---|
| ruff / mypy | 通过 |
| check_contract --meta-json | **通过**："契约文档对照通过"，一共 85 个枚举，URI_TOO_LONG 已在 error_codes 里 |
| check_code_namespaces --meta-json | rc 0 |
| 新增枚举的取值 | PlanStatus、PlanConditionType、SecurityReconciliationKind、SecurityReconciliationSource 与契约 §3 第 431–446 行逐值一致 ✓ |
| errors.py | 加了 URI_TOO_LONG 414，文案"请求地址过长"；后端仍然不会产生这个错误（由网关产生），符合 #34 ✓ |
| tester d018fad 套件跑在本提交上 | 见 review-d018fad（12 failed / 6 errors 都归 tester） |

## 2. 接口探测（这些问题早就存在，不是本提交引入，归 T-B50 / 契约 #30）
| 探测 | 实际 | 契约要求 |
|---|---|---|
| 匿名 POST /trades、/accounts，body 是格式错误的 JSON | 400 VALIDATION_ERROR | **401**（§9 验收 2；架构师裁定：应当先 401） |
| 已登录、不带 CSRF、body 是格式错误的 JSON | 400 | 403 CSRF_FAILED |
| POST /auth/login，带外站 Origin（<url> | 401 INVALID_CREDENTIALS | 403 CSRF_FAILED（§1.3 / 验收 1） |

fb4104a 声称已修复前两项，但还没有评审，第三项（login 不检查 Origin）它没有提到。

## 3. 问题
**B：无。M：无**（本提交范围内）。
- 遗留问题 M（T-B50，不是本提交引入）：上表三项。修法：鉴权和 CSRF（含 login/register 的 Origin 校验）放在 body 解析之前；login 和 register 虽然免 CSRF token，但外站 Origin 必须返回 403。→ 后端 T-B50

## 4. 推送后 CI
| 任务 | 结果 | 归属 |
|---|---|---|
| contract（check_contract / namespaces / meta） | **绿** | — |
| backend：ruff / mypy | 绿 | — |
| backend：pytest | 取决于 tests/backend 是否已合入；T-T01 合入后，按 review-d018fad 会红 | tester |
| frontend | 绿（由 d9c045f 修好） | — |
| migrations | 绿（0018，见 review-9e693b2） | — |
