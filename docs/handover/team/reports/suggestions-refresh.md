# POST /suggestions/refresh —— BLOCKED（未实现，无代码）

按 19:34 指示（“若重算引擎 T-B30/T-B31 不存在，不要写假逻辑，报告缺什么并停止此项”），本项停止。

## 核查结果（2026-11-01，HEAD 后端代码）
- `src/backend/app/signals/`、`app/advice/`、`app/features/`、`app/evaluation/`、`app/signal_rt/` 均为空目录（只有包占位）。
- 代码中没有任何写入 `app.suggestions` 的路径；只有 `app/candidates.py` 读取该表。
- 因此“只用缓存数据同步重算建议”（契约 ~1019 行、changelog #36：200 `{suggestion|null, changed, superseded_id, data_as_of}`；409 `SUGGESTION_REFRESH_TOO_FREQUENT{retry_after_s}`；409 `DATA_LICENCE_UNAVAILABLE`；503 `FRESH_DATA_REQUIRED`）没有可调用的重算函数。

## 缺什么
1. T-B30a 特征库（feature_spec v1.0.1 的特征计算与读取）——本队列最后一项，只做特征，不含策略。
2. T-B30 策略/建议引擎：读特征 → 跑 config/strategies 中的策略 → 生成并写入 `suggestions`（含 superseded 链、`data_as_of`）。
3. T-B31：建议生命周期（替代/失效、频率限制状态的存放位置）。

## 需要谁做什么
- **派单方/架构师**：T-B30、T-B31 派单后再做本端点；建议届时把频率限制的计数口径（每用户每证券？窗口长度在 config 哪个键）一并写明。
- 后端：T-B30/T-B31 落地后实现，约 1 个端点 + 自检。

## 复核（19:56，HEAD 6efedef，按 19:50 新顺序的第 3 项）
- 仍然阻塞：`app/advice/`、`app/signals/`、`app/signal_rt/` 依旧为空，没有任何代码写入 `app.suggestions`；`app/strategy/` 只有卡片/DSL/评估器框架，没有“读缓存 → 产出 Suggestion”的函数。
- 契约 #36 已核对（api-contract v0.2.9 验收第 10 条）：同步、只用缓存、刷新期间 ingest 收不到拉取请求；`200 {suggestion|null, changed, superseded_id, data_as_of}`；首次刷新 `changed=true, superseded_id=null`；无变化时 `suggestion.id` = 当前有效的那条；刷新后 `GET /suggestions?security_code=&status=active&limit=1` 必须等于响应里的 `suggestion`。错误：`409 SUGGESTION_REFRESH_TOO_FREQUENT{retry_after_s}`、`409 DATA_LICENCE_UNAVAILABLE`、`503 FRESH_DATA_REQUIRED{data_as_of}`。
- 第 10 条还依赖 `GET /suggestions`，目前也没有实现（api/v1 下没有 suggestions 路由）。
- 按指示不写假逻辑，本项停止；转去做 T-B49 补充项。
