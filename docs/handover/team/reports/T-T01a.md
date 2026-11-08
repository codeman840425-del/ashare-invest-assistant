# T-T01a 报告（测试角色）

- 工作区：`/workspace/wt-tests-T-T01`（git worktree），分支 `test/T-T01`
- 新提交：**`23fb8b7`**（父提交 `3adfeba`），**只改 `tests/`**，**未推送**
- 仓库外改动：`/workspace/team/reports/T004-import-cases.md`（码改为 v0.2、加变更说明、新增 TC-ENC-12）、本报告
- 共享工作区 `/workspace/ashare-invest-assistant` 未改动；后端与 v0.2 文档通过 `git archive` 导出到 `/tmp/aia-v02` 只读使用（全程 `PYTHONDONTWRITEBYTECODE=1`，导出目录内 0 个 `__pycache__`）
- 未调用麦蕊或任何真实行情 API；没有使用真实 key；本报告不含任何原始敏感值

## 1. 改动文件（28 个，+5051 / −117）

| 文件 | 说明 |
|---|---|
| `fixtures/broker_statements/fmt_a/generate.py` | 新增 `fake_identifiers` 输出：S5/S6（plan 7.4A，ASCII `\b`）逐文件复算，只登记 generate.py 中的 4 个虚构常量；生成 `trades_cr.txt`；`--check` 同时校验 meta.json |
| `fixtures/.../fmt_a/meta.json` | 新增 `fake_identifiers`（description / rules / shareholder_codes / seat_codes / by_file）、`trades_cr.txt` 条目（`line_ending: "CR"`） |
| `fixtures/.../fmt_a/trades_cr.txt` | **新夹具**：GBK、纯 CR 换行，内容与 `trades_lf.txt` 相同（5 条数据行） |
| `fixtures/.../fmt_a/expected.json` | **新文件**：README 旧 §6 迁入，码改为契约 v0.2（§4.1 提示码 / §4 HTTP 码）；22 个文件 + 4 个场景 + 21 个 generated_cases，46 个提示码全覆盖 |
| `fixtures/.../fmt_a/README.md` | §6 改为引用 `expected.json`（键说明、约定、使用者）；§2/§3/§8 同步 |
| `backend/unit/import_codes_v0_2.json` | 契约 v0.2 §4.1 码表快照（46 = 21 error + 25 warning） |
| `backend/unit/test_expected_json.py` | **新**：expected.json ↔ meta.json 一一对应；行状态/去重状态/级别/范围一致；confirm/upload 只用 §4 HTTP 码；46 码全覆盖；文档为 v0.2 时快照 == 契约 §4.1 == plan 3.5A-1，§3 枚举一致 |
| `backend/unit/test_import_codes_generated.py` | **新**：21 个 generated_cases 占位，等 `app.importing.registry` 落地 |
| `backend/unit/test_import_cases_skeleton.py` | 改读 expected.json；54 条（原 53 条 id 与顺序不变，TC-ENC-12 插在 ENC-11 后）；新增覆盖性检查 |
| `backend/unit/import_cases.json` | 新增 TC-ENC-12（`trades_cr.txt` vs `trades_sample.txt`） |
| `backend/unit/test_fixtures_fmt_a.py` | 支持 CR；白名单改读 `fake_identifiers`；逐文件复算 S5/S6 命中数（断言只报文件名与个数，不回显值）；CR≡LF；README §3 表与 meta 一致 |
| `backend/api_app/`（conftest + 7 个测试文件 + `config_defaults_v0_2/*.yaml` 5 个） | **新**：进程内测试 T-B01 后端（见 §3） |
| `requirements-app.txt` | api_app 依赖（版本取自后端 uv.lock） |
| `e2e/playwright.config.ts`、`e2e/README.md` | 静态页默认端口 4173 → **4399**（见 §5 失败 2） |
| `tests/README.md` | 目录表、安装、环境变量、“未实现功能的约定” |

## 2. 待办完成情况

| # | 待办 | 结果 |
|---|---|---|
| 1 | meta.json 加 `fake_identifiers`，`--check` 仍通过 | 完成；`generate.py --check`：21 个输出全部 OK，`0 file(s) differ` |
| 2 | README §6 → `expected.json`（v0.2 码），§6 改为引用；骨架测试读 expected.json；T004 用例表码改 v0.2 + 变更说明 | 完成；结构保持，只追加 1 条（见待确认 4） |
| 3 | 只含 CR 的夹具（generate.py 生成）+ expected 条目 + 用例 | 完成：`trades_cr.txt` / expected `same_as trades_sample.txt` / TC-ENC-12 |
| 4 | yaml 默认值、`/health/live`、`/health/ready`、405 | 完成；对真实后端（v0.2 导出）运行；未实现部分 xfail；`config/*.yaml` 未创建 → skip（依赖 T-B01 后续 / T-B02） |
| 5 | T-B01.md §6 建议的 10 类用例 | 完成，见 §3 映射 |
| 6 | 未实现 → skip/xfail 并写明任务号/模块 | 完成，原因均含 `T-B01 v0.2 修订` / `T-B02` / `app.importing.registry（T-B 系列）` / `T-B 鉴权任务` |
| 7 | 跑全部套件、扫描、本地提交、不推送 | 完成：`23fb8b7`，未推送 |

## 3. T-B01 §6 十类用例 → 测试位置

| T-B01 §6 | 文件（用例数） |
|---|---|
| 1 错误外壳、2 500 不泄露、4 校验错误、405 | `test_errors_and_validation.py`（17） |
| 3 request_id、9 访问日志 | `test_request_id_and_logging.py`（10） |
| 5 分页游标 | `test_pagination.py`（11） |
| 6 /health（含 v0.2 live/ready、心跳 JSON、paused 优先、2s 超时） | `test_health.py`（15，含参数化） |
| 7 /meta/enums（与契约 markdown 逐项比对、ETag/304） | `test_meta_enums.py`（12） |
| 8 配置、10 前缀 | `test_config.py`（19） |
| yaml 默认值（plan v0.2 §6.1） | `test_config_yaml_defaults.py`（10） |

## 4. 运行结果

环境：`tests/.venv`（Python 3.12）；“v0.2”= `AIA_DOCS_DIR=/tmp/aia-v02/docs AIA_BACKEND_DIR=/tmp/aia-v02/src/backend`；“默认”= 本分支自带 docs/src（无 v0.2 文档、后端为骨架）。

| 套件 | 默认环境 | v0.2 环境 |
|---|---|---|
| pytest 全部（backend + replay） | 260 passed, 211 skipped | **368 passed, 84 skipped, 19 xfailed**, 0 failed |
| └ backend/unit | — | 237 passed, 75 skipped |
| └ backend/api_app | 10 passed, 130 skipped（后端不可 import） | 114 passed, 7 skipped, 19 xfailed（连续 3 次结果相同，无抖动） |
| └ backend/integration（testcontainers） | — | 4 passed |
| └ backend/contract（本地桩，服务未起） | — | 3 passed, 1 skipped |
| └ backend/contract（live，对 v0.2 后端起 uvicorn） | — | **4 passed, 2 subtests failed**（见 §5 失败 1） |
| └ backend/golden | — | 5 passed, 1 skipped |
| └ replay | — | 5 passed |
| vitest | 9 passed | — |
| Playwright | 修复前 1 failed / 1 passed / 2 skipped；**修复后 2 passed, 2 skipped** | — |
| `generate.py --check` | 21 OK，0 differ | — |

skip 原因汇总（v0.2 环境）：导入用例骨架 54 条 + generated_cases 21 条 → 等 `app.importing.registry`（T-B 系列）；`config/*.yaml` 5+1 条 → 依赖 T-B01 后续 / T-B02；`/admin` 错方法 1 条 → T-B 鉴权任务；golden 1 条 → strategy_eval 未落地；live 契约（服务未起时）1 条。

19 个 xfail（都是“已落地但与契约 v0.2 不符”，运行时检测）：405 ×3（仍返回 404、无 `Allow`、ErrorCode 缺 METHOD_NOT_ALLOWED）；`/health/live`、`/health/ready` 未实现 ×9；心跳 JSON 格式 ×1；Redis 停时 `ingest=unknown`+503 ×1；`/meta/enums` 枚举、错误码、version/import_codes、命名空间重名（DATA_STALE）×4；yaml 未知键未拒绝（T-B02）×1。

## 5. 失败、复现与日志

**失败 1（未修，属后端缺口 T-B01 v0.2）：live 契约 ST204，未声明的方法返回 404 而不是 405**
- 复现：用 v0.2 导出的后端起服务（另建临时 venv，依赖按 uv.lock：fastapi/pydantic-settings/psycopg[binary] 3.3.6/redis 8.1.0/uvicorn 0.54.0；DB/Redis 指向本机 1 号端口），`uvicorn app.main:create_app --factory --port 8080`，然后 `tests/.venv/bin/pytest tests/backend/contract`
- 日志摘录：
  ```
  - ST204 Wrong response to undeclared method
      Unsupported method TRACE returned 404, expected 405 Method Not Allowed
      curl -X TRACE <url>
  SUBFAILED backend/contract/test_contract_live.py::test_live_api_conforms_to_openapi[GET /api/v1/health]
  SUBFAILED backend/contract/test_contract_live.py::test_live_api_conforms_to_openapi[GET /api/v1/meta/enums]
  ```
  同时 `curl` 结果：`/api/v1/health/live` 404、`/api/v1/health/ready` 404、`/api/v1/health` 200。与 api_app 的 405 / health xfail 一致。live 契约测试是通用 schemathesis 跑法，未加 xfail，后端补 405 后自然通过。

**失败 2（已修，环境冲突）：Playwright 冒烟用例连到了别人的前端预览**
- 现象：`smoke.spec.ts` “视口为 1440×900，深色主题生效” 失败：`Expected pattern: /E2E 冒烟页/  Received string: "A股投资研究与决策助手"`
- 原因：共享工作区里另一个 agent 的 `vite preview --port 4173` 正在监听 4173；配置 `reuseExistingServer: !CI` 直接复用了它。
- 修复：静态页默认端口改为 4399（`E2E_STATIC_PORT` 仍可覆盖），重跑 2 passed / 2 skipped。

开发中已修复的问题（不遗留）：未知 S5 形态命中（expected.json 一处描述里写了第二个虚构<account-field>，改为“运行时按 `^A0{8}[0-9]$` 构造”，仓库中不再出现）；无夹具用例（TC-POS-05、TC-PRIV-01/03/04）被骨架误判为缺期望；`app.importing` 目前只有空的 `parsers/` 目录，占位检测改为 `app.importing.registry`。

## 6. 扫描结果（本次 diff：28 个 tests/ 文件 + T004-import-cases.md，约 254 KB）

| 扫描 | 结果 |
|---|---|
| gitleaks（`zricethezav/gitleaks:latest dir --redact`） | **no leaks found** |
| plan 7.4A S1 / S2 / S3 / S4 / S8 / S9 | 全部 **0** |
| S5 / S6 | 命中**全部**在 `fake_identifiers` 中（6 个文件），登记外 **0** |
| S7（≥3 个交割单表头 / GBK 文本） | 6 个文件：均为 `fixtures/broker_statements/fmt_a/` 合成夹具及其说明文档（README、generate.py、meta.json、expected.json、trades_cr.txt）和 T004 用例表；按 plan 7.4A 需由 DevOps 对该目录做豁免（见待确认 6） |
<redacted:identity-or-account-line>

## 7. 待确认问题

1. **T-B01 相对契约 v0.2 的缺口**（已用 xfail 标出，修好后 strict XPASS 会提醒删标记）：`/health/live`、`/health/ready`；405 + `Allow`；`/meta/enums` 缺 `version`/`import_codes`；枚举改值；`DATA_STALE`→`FRESH_DATA_REQUIRED`；ErrorCode 里仍有 `IMPORT_DUPLICATE_FILE`/`IMPORT_UNRECOGNIZED_FORMAT`/`IMPORT_ROW_COLUMN_MISMATCH`，缺 `IMPORT_FILE_ERRORS`/`IMPORT_NOTHING_TO_COMMIT`/`IMPORT_WARNINGS_UNACKNOWLEDGED`。
2. **yaml**：未知键未拒绝（T-B02）；仓库 `config/` 下还没有 plan §6.1 的 5 个 yaml。测试里的 `config_defaults_v0_2/` 是 plan 块快照，后端建好文件后两者自动比对。
3. **BUSINESS 环境变量与 yaml 是深合并**（pydantic-settings 行为）：只覆盖 `realtime.intervals.quote_interval_s` 时其余键保留。测试按深合并写，请后端确认这是预期语义。
4. **“保持 53 条结构”**：为 CR 夹具追加了 TC-ENC-12，总数 54；原 53 条 id 与顺序不变。若必须恰好 53 条，可把 CR 并入 TC-ENC-11 的夹具列表。
5. 后端代码与 v0.2 文档都还不在 `origin/main`；本分支默认环境下 api_app 与文档比对用例 skip，需设置 `AIA_BACKEND_DIR` / `AIA_DOCS_DIR`。
6. **CI 秘密扫描**：S5/S6 豁免请读 `meta.json.fake_identifiers`（只豁免登记值，逐文件计数），S7 对 `tests/fixtures/broker_statements/`（带 `# SYNTHETIC` 标记）豁免——需 DevOps 实现。
7. 导入规则仍待确认（沿用 T004）：<field:balance>链规则、跳过行的 `dedup_status`、交易日历来源、NAME_MISMATCH 主数据夹具、对账期望、09:25 集合竞价时段、缺列时的格式嗅探。
8. live 契约测试（schemathesis）是否在后端补 405 前加 xfail？目前保持真实失败以暴露问题。

## 8. 复现命令
```bash
cd /workspace/wt-tests-T-T01
export PYTHONDONTWRITEBYTECODE=1 AIA_DOCS_DIR=/tmp/aia-v02/docs AIA_BACKEND_DIR=/tmp/aia-v02/src/backend
tests/.venv/bin/pytest tests/backend tests/replay -p no:cacheprovider
(cd tests/fixtures/broker_statements/fmt_a && ../../../.venv/bin/python generate.py --check)
pnpm -C tests test && pnpm -C tests e2e
```
