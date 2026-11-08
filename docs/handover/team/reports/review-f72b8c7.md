# 评审报告：f72b8c7（T-B03e 追加 / 架构师裁定 T-T23 #1：closed 时注册一律 503）

- 评审对象：`f72b8c7`（父提交 `d26e1d3`，2026-11-02 08:23 UTC+8，仅本地）
- 依据：docs/api-contract.md v0.2.9 第 32 行（#16 T-T23 裁定 1）、第 767 行（/auth/register 判定顺序）、第 1143 行（验收 10：响应体相同、users 无新增、不写蜜罐审计）
- 方式：`git archive f72b8c7` 导出到 /tmp/rv3-f72b8c7，`uv sync --frozen`；同时在当前 HEAD `7a3e9cb` 导出 /tmp/rv3-head 复核。临时容器 timescale pg16（rv3-pg）+ redis（rv3-redis），用 `create_app(Settings(...))` + TestClient 实测；测完已删除。未改代码、未提交、未推送

## 结论：通过

改动很小、方向正确：`require_registration_open` 作为路由依赖（在请求体模型之前求值），再加上 `_RegistrationGateRoute` 在 FastAPI 解析 JSON 之前调用同一判定，保证了 closed 时畸形 JSON 也不会先得到 400。实测 12 种请求体在 closed 下全部 `503 REGISTRATION_CLOSED`，响应体逐字节相同（去掉 request_id 后），audit_logs/users 数量不变；open 模式的正常注册、蜜罐、非法 JSON 400 行为不变；OpenAPI 中路由仍在。HEAD（7a3e9cb，含 T-B47 CSRF 双提交、T-B46 BodySizeLimit 中间件）上复测结果一致。没有 B/M 级问题。

## 问题表

| 级别 | 位置 | 问题原因 | 修复建议 | 归属 |
|---|---|---|---|---|
| m1 | src/backend/app/api/v1/auth.py:58–59 | 路由类里用 `dependency_overrides.get(get_settings, get_settings)()` 直接调用 provider。现在 `create_app(settings)` 的 override 是无参 lambda、`get_settings` 本身也无参，所以没问题；但将来若有人把 override 写成带依赖参数的函数，这里会 TypeError → 500 | 在 docstring 写明“get_settings 的 override 必须是无参可调用”，或改成从 `request.app.state` 取 Settings（create_app 时写入） | 后端（可选） |
| m2 | auth.py:43–47 + 166–168 | 同一判定执行两次（路由类一次、依赖一次）。行为无差别，但以后改判定时容易只改一处 | 保留依赖是为了 OpenAPI/可读性的话，在依赖上注释“真正生效的是路由类”；或删掉依赖 | 后端（可选） |
| m3 | HEAD 上 app/common/middleware.py:74（BodySizeLimitMiddleware，bbf58a0 引入，非本提交） | 请求体超过 `imports.max_request_bytes`（26 MiB）时，中间件在路由之前返回 `413 PAYLOAD_TOO_LARGE`，closed 模式下也是 413 而不是 503。契约第 32 行“不论请求体格式”没有排除超限体 | 架构师在契约里注明“超过框架层上限的请求体仍为 413（传输层，先于一切路由判定）”即可，不建议为此改代码 | 架构师（契约措辞） |
| m4 | src/backend/tests 不存在（既有） | 本提交没有自动化测试，验收 10 只能靠手工 | 测试员把下面“测试方法 2”的矩阵写进集成用例（T-T23） | 测试员 |

## 测试方法

1. 静态检查（/tmp/rv3-ci.sh）：ruff check、ruff format --check（77 个文件）、mypy strict 均通过；scripts/ci/check_contract 等检查通过；scripts/ci/tests 200 passed / 55 skipped；`check_fixtures` 失败为既有问题（三个提交都一样，与本提交无关）。
2. closed 模式（`REGISTRATION_MODE=closed`，`APP_ENV=test`），POST /api/v1/auth/register：

| 请求体 | f72b8c7 | HEAD 7a3e9cb |
|---|---|---|
| 非法 JSON `{bad json` | 503 REGISTRATION_CLOSED | 503 |
| 空体（application/json） | 503 | 503 |
| 无 content-type 空体 | 503 | 503 |
| text/plain | 503 | 503 |
| form 表单 | 503 | 503 |
| JSON 数组 | 503 | 503 |
| `{}` 缺字段 | 503 | 503 |
<redacted:sensitive-value-or-command>
| 带未知字段 | 503 | 503 |
| 蜜罐 website 非空 | 503 | 503 |
| 蜜罐 form_started_at 为未来时间 | 503 | 503 |
| 2 MB 体（未超 26 MiB 上限） | 503 | 503 |

   5 种代表性请求体的（状态码、响应体去 request_id、content-type）集合大小为 1，即响应完全相同；audit_logs、users 计数前后不变（不写蜜罐审计）。
3. 对照（open 模式）：正常注册 201 pending；蜜罐 201 且审计新增 `auth.register_honeypot`；非法 JSON 400 VALIDATION_ERROR；`/auth/login` 非法 JSON 仍 400（其他路由未受路由类影响）；OpenAPI 中 `/api/v1/auth/register` 仍存在。
4. HEAD 复核：c9e1e73 的 CSRF 双提交只改 `current_auth`/`current_admin`，register 不依赖它们，判定顺序不受影响；结果同上表。

## 谁需要做什么

- 后端：无必须项；m1、m2 可在下次碰到 auth.py 时顺手处理。
- 架构师：m3 在契约 #16 / 第 1143 行补一句 413 例外。
- 测试员：把第 2 节矩阵加入 T-T23 集成用例。
