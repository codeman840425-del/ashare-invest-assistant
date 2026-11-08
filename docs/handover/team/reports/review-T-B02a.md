# 评审：T-B02a（ce38a3f、045c550）

- 评审人：架构师；日期：2026-11-01
- 依据：plan.md、api-contract.md v0.2.3（评审时 HEAD cf2ba7a；定夺后 7c62f59）、review-T-B02 的 F1–F11
- 结论：**通过**（无阻断、无主要问题；2 条次要问题、2 条建议，由 T-B03 后续提交顺带处理）

## 1. 验证方式
- 在独立 worktree（f44b6ee，含 T-B02a）里跑 ruff / ruff format --check / mypy：50 个文件全部干净。
- 用测试分支 f545a6a 的 tests 跑：**513 passed，89 skipped，0 failed**。
- Alembic：upgrade head → check（没有新的 op）→ downgrade base → upgrade head，全部通过，head 为 0004。
- 实测：append-only 表 `TRUNCATE` / `UPDATE` 被触发器拒绝（`reject_truncate` / `reject_mutation`）；请求体超限返回 413 信封。

## 2. F1–F11 复核
| # | 原问题 | 状态 | 说明 |
|---|---|---|---|
| F1/F2 | nginx/运维项 | 已关闭 | 运维 2dc2f1b |
| F3 | 测试侧 | 移交 | T-T01c |
| F4 | llm.yaml | 已关闭 | |
| F5 | 同一变量的扁平写法与嵌套写法不一致 | 已关闭 | config.py:221 起：两种写法冲突时报 ConfigError，错误消息只含变量名；残余问题见 N1 |
| F6 | 注释错误 | 已关闭 | |
| F7 | 请求体过大 | 已关闭 | `BodySizeLimitMiddleware`（common/middleware.py:74）同时检查 Content-Length 和流式累计；返回 413 `{max_bytes}` + `Connection: close` |
| F8 | pct 范围 | 已关闭 | 应用层校验 5–50，DB 列加注释 |
| F9 | — | 未关闭 | 移交 T-B04a |
| F10 | — | 延后 | |
| F11 | — | 只改了 docstring | 可接受 |

迁移 0003：semver 列的保护要求表为空、`reject_truncate`、分区保护齐全，downgrade 与 upgrade 对称。

## 3. 发现
| # | 级别 | 位置 | 问题 | 修改 |
|---|---|---|---|---|
| N1 | 次要 | app/config.py:417–424 | `with_business_overrides` 判断"字段值等于旧 YAML 值就跟着刷新"，属于启发式。如果测试构造时显式传入的值恰好等于旧 YAML 值，这个值会被覆盖 | 构造时记录 `ingest_*` 的来源（env/yaml/explicit），只刷新来源为 yaml 的字段；或加注释并补一条测试 |
| N2 | 次要 | app/config_files.py:226–257、app/main.py:46、app/common/errors.py:246、config/ingest.yaml:35 | 上传上限放在 `ingest.imports.*`。T-A05 定为单独的 `config/imports.yaml`，键路径 `imports.*`（`ingest.yaml` 只由 ingest 进程读取） | 把 `IngestImports` 改名为 `ImportsConfig`，挂到 `BusinessConfig.imports`；删去 ingest.yaml 中注释掉的 imports 块；新建 config/imports.yaml；补 `max_rows_per_file`、`allowed_extensions`、`raw_file_retention_days` 三个键（见 plan 6.1） |
| N3 | 建议 | app/config_files.py:241 | `max_request_bytes` 与 nginx `client_max_body_size 26m` 靠人工保持一致 | 让 CI 解析 nginx.conf 并与 imports.yaml 对比 |
| N4 | 建议 | — | `BUSINESS_FILES = tuple(BusinessConfig.model_fields)` 会随模型自动变化 | 定夺后共 8 个文件（新增 imports、auth），请同步白名单相关测试 |
