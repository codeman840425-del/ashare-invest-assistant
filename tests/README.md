# tests/ —— 测试（测试角色）

T-T01 建立的测试框架。布局对齐 plan §6 / §8.0：

| 目录 | 框架 | 说明 |
|---|---|---|
| `backend/unit/` | pytest + hypothesis | 纯函数；现含 fmt_a 夹具守卫（含 fake_identifiers / CR 换行）、`expected.json` 与 v0.2 §4.1 码表一致性、T004 导入用例骨架（54 条，T-T01a 增 TC-ENC-12）、`generated_cases` 占位、麦蕊拦截自检 |
| `backend/api_app/` | pytest + FastAPI TestClient | T-T01a：进程内 import 后端 `app.main.create_app`（T-B01）——配置默认值 / yaml、健康检查、405、统一错误、校验、分页、`/meta/enums`、request_id 与日志脱敏；依赖 `requirements-app.txt`，缺包或后端不可 import 时整组 skip |
| `backend/integration/` | pytest + testcontainers | PostgreSQL 16 + TimescaleDB、Redis 7 测试容器；**Docker 不可用自动 skip** |
| `backend/contract/` | schemathesis | 契约脚手架：本地 WSGI 桩（可运行示例）+ 对真实后端（服务不可达 skip） |
| `backend/golden/` | pytest + 快照 JSON | 策略/建议 golden 用例，见该目录 README |
| `replay/` | pytest + FakeClock | 麦蕊录制回放，见该目录 README |
| `frontend/` | vitest + testing-library（jsdom） | 前端单元测试 |
| `e2e/` | Playwright（1440×900 深色） | 端到端测试 |
| `fixtures/broker_statements/fmt_a/` | — | 合成交割单夹具（T004；T-T01a 增 `trades_cr.txt`、`expected.json`、meta.json `fake_identifiers`） |
| `fixtures/mairui/` | — | 麦蕊响应录制（脱敏、无 licence；目前只有合成示例） |

## 准备（在仓库根目录执行）
```bash
# Python 3.12
uv venv --python 3.12 tests/.venv
uv pip install --python tests/.venv/bin/python -r tests/requirements.txt
uv pip install --python tests/.venv/bin/python -r tests/requirements-app.txt   # backend/api_app 需要
# Node ≥ 20 + pnpm
pnpm -C tests install
pnpm -C tests e2e:install          # 下载 chromium
```

## 运行
```bash
tests/.venv/bin/pytest tests/backend tests/replay     # pytest（rootdir=tests，读 tests/pytest.ini）
pnpm -C tests test                                    # vitest
pnpm -C tests e2e                                     # Playwright
```

可选环境变量：
| 变量 | 作用 |
|---|---|
| `AIA_TEST_DATABASE_URL` / `AIA_TEST_REDIS_URL` | 复用已有 PG / Redis（如 CI service），不启动容器 |
| `AIA_TEST_PG_IMAGE` / `AIA_TEST_REDIS_IMAGE` | 覆盖测试容器镜像（默认与 compose 一致） |
| `AIA_CONTRACT_BASE_URL`（默认 `http://127.0.0.1:8080`）/ `AIA_OPENAPI_PATH`（默认 `/api/v1/openapi.json`） | live 契约测试目标 |
| `AIA_BACKEND_DIR`（默认 `src/backend`）/ `AIA_DOCS_DIR`（默认 `docs`）/ `AIA_CONFIG_DIR`（默认 `config`） | api_app 与码表测试的后端、文档、配置位置；文档不是 v0.2 时相关比对用例 skip |
| `E2E_BASE_URL` | Playwright 目标站点；不设则用本地静态页跑示例 |

Docker 需要当前用户能访问 daemon（`docker info` 成功）；否则 integration 用例 skip。

## 未实现功能的约定
尚未落地的模块一律 `skip`（写明依赖的任务号/模块，如 `app.importing.registry`、T-B02）；已落地但与契约 v0.2 不符的行为用 `xfail(strict=True)` 标出差异，修好后会 XPASS 失败提醒删除标记。

## 硬规则
- **永不调用麦蕊或任何真实行情 API**：`tests/conftest.py` 拦截麦蕊域名并把 `MAIRUI_LICENCE` 置空；行情一律用 `fixtures/mairui/` 回放或 mock。
- 不提交任何真实交割单、股东代码、资金账号、licence；`fixtures/broker_statements/` 只放合成样本（plan §3.5A）。
- 虚拟环境、node_modules、报告产物见 `tests/.gitignore`，不入库。
