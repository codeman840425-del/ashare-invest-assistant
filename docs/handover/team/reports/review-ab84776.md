# 评审 ab84776（G-7：列表接口 account_id 越权 → 404）

- 评审人：项目架构师；时间：2026-11-01 20:15（America/Denver，UTC-7）
- 方式：只读。在 /tmp 的干净导出（git archive ab84776，后端 `uv sync --frozen`）里做；临时容器 rv1101-pg（timescale pg16）、rv1101-redis 只绑 <host>，角色口令是一次性随机 hex；未推送，未调用麦蕊。
- 对照：契约 v0.2.9 #27 ⑦（§7.5、§7.6）；父提交 2d46332（运维，不在本次范围）。

## 结论：可以推送

改动很小，只在两个列表接口加了 owned_account 校验，没有发现问题。

## 1. 实测

| 项 | 结果 |
|---|---|
| selfchecks/g7.py（真实 PG） | **22 passed / 0 failed** |
| ruff / mypy | 通过 |
| check_contract（只看文档）/ check_code_namespaces | rc 0 |
| check_contract --meta-json | **失败**：缺 plan_condition_type、plan_status（来自契约 #30，基线就是红的，不是本提交引入；d3be426 修好） |
| tester cd65fd6（G-7 用例） | 列表 account_id 非本人 → 404 的用例与实现一致 |

## 2. 核对

| 说法 | 核对 |
|---|---|
| GET /imports?account_id= 非本人/不存在/已归档 → 404 | ✓ src/backend/app/api/v1/imports.py:471–473 调 owned_account（accounts.py:59–70：id + user_id + archived_at IS NULL，不区分原因） |
| GET /trades?account_id= 同上 | ✓ trades.py:244–245，同一个连接里先校验再加筛选条件 |
| 响应体与 /portfolio 一致 | ✓ 同一个 AppError(NOT_FOUND) |
| 其他带 account_id 查询参数的接口 | 全仓只有 imports、trades、portfolio 三处，均已用 owned_account ✓ |

## 3. 问题

**B：无。M：无。**

**m**
- m1（nit）imports.py:471 为校验单独开了一个 `engine.connect()`，查询主体又开一个；trades.py 是同一个连接。功能没问题，后续顺手统一即可。→ 后端

## 4. 推送后 CI

| 任务 | 结果 | 归属 |
|---|---|---|
| backend（ruff/mypy/pytest） | ruff/mypy 绿；pytest 取决于 tests/backend 是否已合入 main（T-T01 未合入前没有用例可跑，属已知问题） | tester |
| contract（--meta-json） | **红**（plan_status/plan_condition_type 缺失，基线已红） | 后端 T-B50，d3be426 修复 |
| frontend / migrations | 不涉及，保持原状 | — |

所以不要单独停在本提交，至少连推到 d3be426。

## 5. 谁做什么
- 后端：无必做项（m1 可选）。
- tester：无。
