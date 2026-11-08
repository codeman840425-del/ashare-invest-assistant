# T-live-0f8129b：aia-t01 live 复测（0f8129b / T-O13 之后）

- 执行：测试；时间 2026-11-01 18:46–18:48 MST（UTC-7）= 2026-11-02 09:46–09:48 Asia/Shanghai
- 目标：nginx <url> aia-t01，部署目录 /workspace/aia-t01-deploy-o11，HEAD 28323bf = T-O13 nginx 动态解析上游，后端代码仍为 0f8129b；api 镜像 sha256:31e17ef4995e…，api 启动于 18:43:51 MST，nginx 18:41:41 MST）
- **只有 T-O13 之后的复测计入结论**。T-O13 前（18:34 MST）跑过一轮 live 契约：3 failed / 21 passed，失败原因与下文 F-1 相同，仅作参考。
- 健康等待：每 30 s 探一次 /healthz 与 /health/ready；检测到 api/nginx 重启后，连续 200 满 121 s（18:44:10–18:46:10 MST）才开始复测。窗口期间未见 502/503。
- 被测代码：worktree `test/T-T01` 已提交的 HEAD **d0ca02d**（用 `git archive` 导出到 /tmp/tlive/head 运行）。worktree 里另一位同学的未提交改动（test_r11_exceptions.py、test_contract_live.py 等）**不在本次范围**；直接在 worktree 里跑会把这些 WIP 用例算进来（我误跑过一次：14 failed，全部来自 test_r11_exceptions.py，不计入）。
- 未提交、未推送；没有修改 tests/、/workspace/aia-t01-deploy*、共享 worktree；没有写 be-b03a-pg；没有调用麦蕊或真实行情 API（MAIRUI_LICENCE/DEEPSEEK_API_KEY 置空）。

## 1. 计数

| 组 | 命令要点 | 结果 |
|---|---|---|
| A. live 契约（tests/backend/contract：schemathesis GET 全量、auth 冒烟、网关 request_id/405/413/healthz、stub） | `AIA_CONTRACT_BASE_URL=<url> pytest tests/backend/contract` | **38 passed / 2 failed**（junit 40 条，含 17 个 schemathesis 子用例通过） |
| B. meta/迁移/T-A11 契约（进程内，后端代码 = 部署目录 src/backend；PG/Redis 为一次性 testcontainers，不碰 aia-t01 库与 be-b03a-pg） | `AIA_BACKEND_DIR/AIA_DOCS_DIR/AIA_CONFIG_DIR=/workspace/aia-t01-deploy-o11/... PYTHONPATH=$AIA_BACKEND_DIR pytest test_meta_enums.py test_contract_t_a11_t_f22.py test_auth_t_b03.py::test_alembic_head_is_known` | **32 passed / 0 failed / 18 xfailed（严格 xfail，均为已登记的后端缺口）** |
| C. live 直接核对 | curl / psql 只读 | 见下 |
| **合计** | | **70 passed / 2 failed / 18 xfailed** |

C 组 live 核对（T-O13 后）：
- /healthz、/health/live、/health/ready、/api/v1/health/live、/api/v1/health/ready 均 200。
- `GET /api/v1/meta/enums` → 200，`version=v0.2.9`，78 个枚举，`X-Request-Id: req_d758eaf56640452cd2e3d9f9a2d681a2`；`candidate_signal_event_cause` ✅；**缺 `candidate_decision`、`research_candidate_origin`、`research_candidate_status`**（与运维所述一致）。
- 迁移版本：aia-t01-postgres-1 `SELECT version_num FROM alembic_version` → **0014** ✅。worktree HEAD 的 `KNOWN_HEADS` 已含 0014（7489eaf），`test_alembic_head_is_known` 通过，无差异。
- `GET /api/v1/meta/registration` → `{"mode":"closed"}`。

## 2. 失败

### F-1　nginx 对超长 URI 返回 HTML 414（2 条 schemathesis 子用例；归属：**运维**，后端/架构师配合在 OpenAPI 声明）
- 用例：`test_contract_live.py::test_live_api_conforms_to_openapi[GET /api/v1/accounts]`、`[GET /api/v1/imports/{batch_id}/rows]`。schemathesis 随机生成，同一根因在各轮还命中过 `/api/v1/imports`、`/api/v1/trades`（T-O13 前一轮：accounts、imports/{batch_id}/rows、trades）。
- 日志摘要：
  - `[414] URI Too Long`，响应体 `<html>…<h1>414 Request-URI Too Large</h1>…nginx…`
  - `AcceptedNegativeData`：负向数据（cursor 超过 maxLength / limit=null 等）没有被以 4xx 契约码拒绝（期望 400/401/403/404/405/406/409/415/422/428/429/5xx，414 不在 OpenAPI 中）
  - `UndefinedContentType`：Received `text/html`，Documented `application/json; charset=utf-8`
- 复现：`curl -s -o /dev/null -w '%{http_code} %{content_type}\n' "<url> -c 'print("A"*20000)')"` → `414 text/html`（T-O13 后仍复现）。
- 原因：请求行超过 nginx `large_client_header_buffers`，nginx 自答 HTML，请求没有到达后端；契约要求所有错误都是 JSON 信封并带 request_id（413 已按此处理，`test_413_payload_too_large_json_envelope` 通过）。
- 建议：运维在 nginx 给 414（以及 400 请求头过大/494）配 `error_page` → JSON 信封 + X-Request-Id（同 413 的做法）；后端/架构师决定是否在 OpenAPI 声明 414（或统一错误码，如 `URI_TOO_LONG`），否则 schemathesis 仍会报 AcceptedNegativeData。
- 非本次回归：0f8129b 部署前后、T-O13 前后都存在。

## 3. 缺口（不算测试失败）

| # | 缺口 | 证据 | 归属 |
|---|---|---|---|
| G-1 | `/meta/enums` 缺 `candidate_decision`、`research_candidate_origin`、`research_candidate_status`（契约 v0.2.9） | live 直查；`test_meta_enums.py::test_enum_names_and_values_match_contract` 与 `test_a11_01_meta_enums` 严格 xfail，原因文本即这 3 个 | **后端**（T-B10 / T-B33） |
| G-2 | `/candidates*` 未实现；F22 resume 幂等/暂停通知未做 | `test_contract_t_a11_t_f22.py` 其余 16 条严格 xfail | **后端**（T-B10、T-B45/T-B03e） |
| G-3 | **登录态上传未执行：aia-t01 没有测试账号** | tests/ 的 conftest、README、e2e 配置都没有测试账号配置（现有 live 用例只发未登录请求）；deploy env（.env 只列出键名核对）与 secrets 目录里也没有账号项；aia-t01 只读查询 `app.users` = **0 行**；注册 `mode=closed`。按规则不新建账号，停止上传 | **运维**（在 aia-t01 用后端 CLI/种子创建专用测试账号，把凭据放进仓库外的 secrets 文件，例如 `~/.config/aia/secrets/aia/test_account`，权限 600，并告知测试变量名）；**测试**拿到后补跑 |
| G-4 | `test_a11_01_db_check_matches_contract` 单独或按文件运行时 `ModuleNotFoundError: No module named 'app'`（依赖别的用例先把后端目录加进 sys.path）；加 `PYTHONPATH=$AIA_BACKEND_DIR` 后通过 | B 组首次运行 1 failed，单测复现；加 PYTHONPATH 后 1 passed | **测试**（用例自身应 importorskip/插入 BACKEND_DIR；本任务不改 tests/，留给 worktree 负责人） |
| G-5 | tests/.venv 缺 argon2/testcontainers 相关依赖时 api_app 整组 skip（README 要求用后端 venv）；本次另建 /tmp/tlive/venv（tests/requirements*.txt + 后端 pyproject） | — | 测试（文档提示，低优先级） |

## 4. 登录态上传（第 2 项）

- **未执行**（T-O13 前后都没有执行），原因见 G-3：找不到现有测试账号，aia-t01 用户表为空，注册关闭；按规则不新建账号。
- 因此**没有上传、没有在 aia-t01 留下数据**：复测后只读检查 `app.users`=0、`app.import_batches`=0，无需清理。
- 补跑预期（拿到账号后）：`POST /api/v1/auth/login`（Cookie + CSRF 双提交，X-CSRF-Token 与 Cookie 对比）→ multipart `POST /api/v1/imports` 上传 `fmt_a/trades_sample.txt` → 对照 expected.json：`parser_id=tdx_trades_v1`、`encoding=gbk`、批次状态 `previewed`、`row_counts` ok 55 / warning 11 / error 0 / skipped 0（共 66 行；warning = 4 条 IMPORT_MISSING_OPENING_POSITION + 7 条 IMPORT_CASH_CHAIN_BREAK）、响应头与信封 request_id 一致；预览后用 `POST /api/v1/imports/{batch_id}/discard` 清理（不 confirm，不写 trades）。

## 5. 产物
- 日志：/tmp/tlive/contract4.log（A 组正式）、/tmp/tlive/offline3.log（B 组正式）、/tmp/tlive/mon2.log（健康等待）、/tmp/tlive/contract.log（T-O13 前，参考）、/tmp/tlive/contract2.log（误跑 WIP，不计）
- 报告和日志中没有密码、token、Cookie、licence 原值。
