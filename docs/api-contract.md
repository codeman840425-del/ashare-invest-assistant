# A股个人投资研究与决策助手 · REST 接口契约（MVP v1）

- 作者：架构师；日期：2026-11-01；状态：待评审
- 配套：[`plan.md`](./plan.md)（架构方案）。本契约优先于代码：FastAPI 生成的 `openapi.json` 与本文不一致时**改代码**。
- **示例值全部虚构**：代码用 `600000.SH / 000001.SZ`，ID 用 `00000000-0000-4000-8000-0000000000xx`，金额为随意整数；不含任何真实账户、股东代码、姓名、金额或委托/成交编号。

---

## 1. 通用约定
| 项 | 约定 |
|---|---|
| 基础路径 | `/api/v1`；JSON，`Content-Type: application/json; charset=utf-8`（文件上传为 `multipart/form-data`；SSE 为 `text/event-stream`） |
| 命名 | 字段 `snake_case`；枚举值小写 `snake_case` |
| ID | UUID v4 字符串（`string(uuid)`） |
| 时间 | `string(datetime)`：ISO 8601 含时区，服务端统一输出 `+08:00`；日期 `string(date)` = `YYYY-MM-DD`（交易日按北京时间） |
| 金额/价格/数量/比例 | **十进制字符串** `string(decimal)`，如 `"10.25"`、`"0.1530"`；不用 JSON number，避免浮点误差。百分比字段名以 `_pct` 结尾，值为百分数（`"3.20"` = 3.20%） |
| 分数/置信度数值 | `number`（0–100 整数分数；0–1 置信度两位小数），是规则计算结果，非金额 |
| 证券代码 | `string`：`{6位代码}.{SH|SZ|BJ}`；指数同格式（如 `000300.SH`） |
| 可空 | 标记为 `T | null` 的字段总是出现，值可为 `null`；未标记的字段必有值 |
| 版本 | 破坏性变更走 `/api/v2`；新增字段不算破坏性，客户端须忽略未知字段 |
| 请求追踪 | 响应头 `X-Request-Id`；客户端可传入同名头 |
| 幂等 | 创建类 `POST` 支持 `Idempotency-Key` 头（24 小时内同键同体返回首次结果，同键异体 → `409 IDEMPOTENCY_CONFLICT`） |

### 1.1 数据状态（凡含行情/因子/建议的响应都带）
```json
{"data_status": "fresh", "data_as_of": "2026-11-02T10:31:00+08:00", "gaps": [{"key": "news", "reason": "no_source", "message": "本产品不提供新闻资讯"}]}
```
- `data_status: "fresh" | "stale" | "pending" | "partial" | "unavailable"`：`stale`=超过刷新间隔 ×2 未更新（0A.3）；`pending`=已投递按需拉取任务；`partial`=部分维度缺数据；`unavailable`=上游不可用。
- `gaps[]: {key: string, reason: "no_source"|"not_yet_published"|"upstream_error"|"quota_deferred"|"user_input_missing", message: string}`。

### 1.2 分页（游标）
- 请求：`?limit=`（默认 50，最大 200）`&cursor=`（不透明字符串）。
- 响应：`{"items": [...], "next_cursor": "string | null"}`；`next_cursor=null` 表示最后一页。排序固定且稳定（默认 `created_at desc, id desc`），各接口另注明。
- 少量小集合接口（枚举、设置）直接返回数组或对象，不分页（注明"不分页"）。

### 1.3 认证与安全
- **会话 Cookie** `sid`：`HttpOnly; Secure; SameSite=Lax; Path=/`；服务端会话存 Redis，空闲 7 天过期（可配置）。
- **CSRF**：登录成功后响应体与 Cookie `csrf_token`（非 HttpOnly）给出令牌；所有 `POST/PUT/PATCH/DELETE` 必须带头 `X-CSRF-Token`，缺失或不符 → `403 CSRF_FAILED`。
- **权限**：未登录 → `401 AUTH_REQUIRED`；账号非 `approved` → `403 ACCOUNT_NOT_APPROVED`；`/admin/*` 需 `role=admin` → 否则 `403 FORBIDDEN`。用户只能访问自己的资源，访问他人资源一律 `404 NOT_FOUND`（不泄露存在性）。
- **合规门槛**：建议类接口（标 ⚖：`/today`、`/suggestions*`、`/daily-reports*`、`/signals*`、`/candidate-signals*`、`/plan-drafts*` 的生成与确认、`/stream` 中标 ⚖ 的事件）要求用户已完成风险测评并同意 `signal_risk_disclosure`，否则 `403 CONSENT_REQUIRED`（`details.required: ["signal_risk_disclosure"]`）。
- **限速**：超限 `429 RATE_LIMITED`，头 `Retry-After`（秒）。
- 敏感字段一律掩码输出（如 `shareholder_code_masked: "A00****000"` 为格式示意），任何接口都不返回原始股东代码、资金账号或原始上传文件内容。

---

## 2. 统一错误格式
```json
{"error": {"code": "VALIDATION_ERROR", "message": "参数校验失败", "details": {"fields": [{"field": "limit", "issue": "must be <= 200"}]}, "request_id": "req_9f8e7d"}}
```
| 字段 | 类型 | 说明 |
|---|---|---|
| `error.code` | string | 机器可读错误码（第 4 节），稳定 |
| `error.message` | string | 中文可读信息，可变，客户端不得据此判断逻辑 |
| `error.details` | object \| null | 结构化细节，按错误码约定 |
| `error.request_id` | string | 与响应头 `X-Request-Id` 一致 |

---

## 3. 枚举（`GET /meta/enums` 返回同一份，不分页）
| 枚举 | 取值 |
|---|---|
| `account_status` | `pending` `approved` `rejected` `disabled` |
| `role` | `user` `admin` |
| `epistemic_type` | `fact` `estimate` `hypothesis` `execution` |
| `horizon` | `intraday_t` `short` `swing` `long` |
| `dimension` | `technical` `capital` `fundamental` `sentiment` `sector_market` `news` |
| `dimension_view` | `bullish` `bearish` `neutral` `unknown` |
| `rule_role` | `entry` `hold` `weakening` `exit` `filter` `veto` `counter` `invalidation` |
| `action` | `buy` `add` `hold` `reduce` `sell` `wait` |
| `t_leg` | `sell_first` `buy_first` （仅 `intraday_t`） |
| `confidence_level` | `high` `medium` `low` |
| `consensus_status` | `unanimous` `divergent` `single` `none` |
| `suggestion_origin` | `daily_batch` `intraday_event` `manual_refresh` |
| `suggestion_status` | `active` `superseded` `invalidated` `expired` |
| `risk_control` | `stop_take`(RC1) `position_cap`(RC2) `total_exposure`(RC3) `sector_concentration`(RC4) `loss_streak_drawdown`(RC5) `plan_violation`(RC6) |
| `risk_level` | `info` `warning` `critical` |
| `market_regime` | `uptrend` `range` `downtrend` |
| `notification_kind` | `suggestion_change` `invalidation` `daily_report` `alert` `import` `system` `reason_released` `plan_draft_ready` `plan_triggered` `strategy_health` |
| `severity` | `info` `attention` `important` |
| `channel` | `in_app` `email` `wecom_app`（预留） |
| `data_status` | 见 1.1 |
| `trade_side` | `buy` `sell` |
| `import_status` | `uploaded` `parsing` `preview_ready` `confirmed` `failed` `reverted` |
| `card_completeness` | `draft` `documented` `runnable_candidate` `promoted` `retired` |
| `lifecycle` | `draft` `simulating` `published` `observing` `retired` |
| `instance_status` | `proposed` `active` `paused` `archived` |
| `candidate_signal_state` | `open` `drafted` `blocked` `released` `confirmed` `dismissed` `expired` `invalidated` `superseded` |
| `reason_code` | 见 6.1（23 个） |
| `reason_status` | `active` `released` `obsolete` |
| `check_on` | `tick` `daily_close` `schedule` `holding_change` `cash_update` `import` `plan_change` `user_action` |
| `release_kind` | `expr` `time` `event` `user_action` |
| `plan_draft_status` | `pending` `confirmed` `discarded` `expired` `stale` |
| `plan_origin` | `manual` `plan_draft` |
| `restriction_kind` | `blocklist` `cooling_off` `mute` |
| `suggestion_user_action` | `viewed` `dismissed` `draft_requested` `draft_confirmed` `reason_manually_released` `acted_trade_linked`（没有 `converted_to_plan`） |
| `feature_status` | `declared` `verified_doc` `verified_live` `gap` `deprecated` |
| `gate` | `G1`–`G7`（plan.md 2.5.13） |
| `llm_task` | `suggestion_rationale` `daily_report_stock` `daily_report_summary` `strategy_divergence` `announcement_title_digest` |

---

## 4. 错误码表
| HTTP | code | 场景 | `details` |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | 参数/请求体校验失败 | `{fields:[{field, issue}]}` |
| 400 | `INVALID_CURSOR` | 游标无效或过期 | — |
| 401 | `AUTH_REQUIRED` | 未登录或会话过期 | — |
| 401 | `INVALID_CREDENTIALS` | 用户名或密码错误（不区分哪一项） | — |
| 403 | `ACCOUNT_NOT_APPROVED` | 账号待审核/已驳回/已禁用 | `{status}` |
| 403 | `ACCOUNT_LOCKED` | 连续失败临时锁定 | `{retry_after_s}` |
| 403 | `CSRF_FAILED` | CSRF 令牌缺失/不符 | — |
| 403 | `FORBIDDEN` | 角色不足 | — |
| 403 | `CONSENT_REQUIRED` | 缺少必要同意或风险测评 | `{required:[string]}` |
| 403 | `ENTITLEMENT_LIMIT_REACHED` | 超出套餐权益上限（自选数、重点关注数、导入次数、LLM 解释次数等） | `{key, limit, current}` |
| 404 | `NOT_FOUND` | 资源不存在或不属于当前用户 | — |
| 409 | `CONFLICT` | 唯一约束冲突（如用户名已存在） | `{field}` |
| 409 | `IDEMPOTENCY_CONFLICT` | 同一幂等键、不同请求体 | — |
| 409 | `VERSION_CONFLICT` | 乐观锁版本号不符（`If-Match`/`base_version_no`） | `{current_version_no}` |
| 409 | `IMMUTABLE_RESOURCE` | 试图修改不可变对象（建议、已发布策略版本、日报、成交原记录） | — |
| 409 | `IMPORT_DUPLICATE_FILE` | 同一文件（内容哈希）已导入 | `{batch_id}` |
| 422 | `IMPORT_UNRECOGNIZED_FORMAT` | 无法识别文件格式/编码 | `{candidates:[{parser, score}]}` |
| 422 | `IMPORT_ROW_ERRORS` | 确认导入时仍有未处理错误行 | `{error_rows}` |
| 422 | `STRATEGY_INVALID_CONFIG` | 策略配置校验失败（未知因子、表达式语法、参数越界） | `{errors:[{path, issue}]}` |
| 422 | `STRATEGY_EXPR_FORBIDDEN` | 规则表达式含非白名单字段或运算 | `{rule_id, token}` |
| 409 | `STRATEGY_VERSION_PUBLISHED` | 已发布版本不可修改 | `{version_no}` |
| 403 | `STRATEGY_NOT_OWNED` | 修改内置策略或他人策略（须先复制） | — |
| 422 | `STRATEGY_HORIZON_MISMATCH` | 给股票绑定的策略不支持所选周期 | `{strategy_key, horizons}` |
| 422 | `RISK_CONTROL_INVALID_PARAMS` | 风控阈值越界 | `{control, fields}` |
| 409 | `SUGGESTION_SUPERSEDED` | 对已被取代的建议执行动作 | `{current_id}` |
| 409 | `SUGGESTION_REFRESH_TOO_FREQUENT` | 手动刷新过于频繁（受权益 `realtime.min_notify_interval_s` 约束） | `{retry_after_s}` |
| 422 | `SUGGESTION_INSUFFICIENT_DATA` | 必备字段缺失，未生成建议（0A.2 缺一不可） | `{missing:[string]}` |
| 422 | `IMPORT_ROW_COLUMN_MISMATCH` | **行级**错误码（出现在 `/imports/{id}/rows` 的 `error_code`，不作为 HTTP 错误）：列数或列名与识别的模板不一致 | — |
| 409 | `INVALID_STATE_TRANSITION` | 状态机不允许的跃迁（第 6.0 节） | `{from, to, allowed}` |
| 409 | `STRATEGY_VERSION_NOT_RUNNABLE` | 模板版本不是 `published`/`observing`（例如 simulating、retired） | `{lifecycle}` |
| 422 | `STRATEGY_FIT_ACK_REQUIRED` | 周期分类器判定不适合，需要用户确认 `fit_ack` | `{horizon, suitable}` |
| 422 | `STRATEGY_PARAM_OUT_OF_RANGE` | 参数覆盖超出 param_schema 的 min/max/choices | `{param, min, max, choices}` |
| 422 | `INSTANCE_SCOPE_INVALID` | 实例作用范围不合法（例如 security 范围缺少代码，或代码不在账户/自选中） | `{scope}` |
| 422 | `PROMOTION_GATES_NOT_MET` | 晋级或上线时门禁未通过 | `{gates:[{gate, result}]}` |
| 422 | `CARD_IMPORT_INVALID` | 导入器校验研究员文档失败（plan.md 2.5.14，只在管理端/CI 出现） | `{file, block, errors:[{path, issue}]}` |
| 422 | `COMPLIANCE_LINT_FAILED` | 用户可见文案含禁用词 | `{terms}` |
| 500 | `SIGNAL_NOT_EXPLAINABLE` | 内部：信号缺少可解释字段，已拒绝写入（只出现在日志和管理端，不返回给普通用户） | `{missing}` |
| 422 | `PLAN_REQUIRES_EXPLAINABLE_SIGNAL` | 草案引用的信号没有通过的规则引用（只有模型输出） | `{signal_ids}` |
| 409 | `SIGNAL_NOT_EXECUTABLE` | 信号仍有生效的不可执行原因 | `{reason_ids}` |
| 409 | `PLAN_DRAFT_STALE` | 草案已过期，或依据的数据/持仓已变化 | `{status}` |
| 422 | `CHECKLIST_INCOMPLETE` | 判断清单必答项未答 | `{missing}` |
| 422 | `RISK_ACK_REQUIRED` | 未确认风险提示 | — |
| 422 | `DEVIATION_ACK_REQUIRED` | 数量或价格超出草案区间，且未确认偏离 | `{fields}` |
| 409 | `REASON_NOT_MANUALLY_RELEASABLE` | 该原因可由系统判断，不能手动解除 | `{code}` |
| 503 | `REGISTRATION_CLOSED` | 注册已关闭（邀请制） | — |
| 503 | `DATA_STALE` | 只用于明确要求最新数据的操作（例如手动刷新）；读接口一律返回 200 加 `data_status`，不报此错 | `{data_as_of}` |
| 503 | `INGEST_PAUSED` | 采集服务被管理员暂停或冷备切换中（只用于需要触发拉取的操作） | — |
| 503 | `LLM_UNAVAILABLE` | 所有 LLM 路由失败（只在显式请求 LLM 时返回；建议本身回落模板，不报错） | `{task}` |
| 429 | `LLM_BUDGET_EXCEEDED` | LLM 日预算用尽 | `{task, budget}` |
| 422 | `LLM_PROVIDER_TEST_FAILED` | 管理员测试连接失败 | `{provider_id, status, message}` |
| 502 | `UPSTREAM_ERROR` | 麦蕊返回错误（已映射，不含 licence） | `{provider:"mairui", upstream_code}` |
| 503 | `UPSTREAM_RATE_LIMITED` | `ingest` 令牌桶耗尽或上游限流，请求已排队（Web 进程不直连麦蕊） | `{retry_after_s}` |
| 503 | `UPSTREAM_UNAVAILABLE` | 上游不可用或证书过期，降级中 | — |
| 429 | `RATE_LIMITED` | 本站限速 | `{retry_after_s}` |
| 500 | `INTERNAL_ERROR` | 未预期错误 | — |
| 503 | `MAINTENANCE` | 维护模式 | — |

---
## 5. 共享对象（各接口复用）
| 对象 | 结构 |
|---|---|
| `Evidence` | `{id: string, key: string(feature_key), value: string \| number \| boolean \| null, unit: string \| null, provider: "mairui" \| "local" \| "user_import", endpoint: string \| null, data_as_of: string(datetime), fetched_at: string(datetime), epistemic_type}` |
| `RuleRef` | `{rule_id: string, snippet_id: string(uuid) \| null, snippet_version: int \| null, role: rule_role, dimension: dimension, passed: boolean, value: string \| null, threshold: string \| null, evidence_ids: string[]}` |
| `ModelRef` | `{model_key: string, version: string, role: "auxiliary", output: object, evidence_ids: string[]}` — `role` 只允许为 `auxiliary` |
| `TextWithEvidence` | `{text: string, expr: string \| null, evidence_ids: string[]}`，用于 `counter_evidence[]`、`invalidation[]`、`reasons[]` |
| `Stat` | `{value: string(decimal) \| null, n: int, window: string, small_sample: boolean}`。n < 20 时 `small_sample=true`；n < 5 时 `value=null`（2.12.3）。**所有胜率、收益、IC、CAR 都用这个结构** |
| `ReleaseCondition` | `{kind: "expr" \| "time" \| "event" \| "user_action", expr: string \| null, at: string(datetime) \| null, event: string \| null, action: string \| null, check_on: check_on[], human_text: string, machine_checkable: boolean}` |
| `RiskFlag` | `{control: risk_control, level: risk_level, message: string, gated_actions: action[], quantity_cap: string(decimal) \| null, evidence_ids: string[]}` |
| `DataStatusBlock` | 1.1 节的 `{data_status, data_as_of, gaps[]}` |

**可解释性强制规则（P1）**：在任何返回 `CandidateSignal`、`Suggestion` 中策略结论的响应里，`rule_refs`、`evidence`、`counter_evidence`、`invalidation` 都是**非空数组**；`model_refs[*].role == "auxiliary"`。服务端写入时校验，不满足的不写入（内部记 `SIGNAL_NOT_EXPLAINABLE`）；契约测试检查所有示例和响应（T-T17）。

---

## 6. 状态机与原因码

### 6.0 状态机（非法跃迁 → `409 INVALID_STATE_TRANSITION`，`details: {from, to, allowed: []}`）
| 对象 | 状态 | 允许的跃迁（触发方） |
|---|---|---|
| 卡片 `card_completeness` | `draft` `documented` `runnable_candidate` `promoted` `retired` | 系统自动计算，客户端不可写 |
| 模板版本 `lifecycle` | `draft` `simulating` `published` `observing` `retired` | draft→simulating（管理员，G1–G7 通过）；simulating→published（管理员，满足 2.5.13 条件）；published⇄observing（健康度状态机，系统）；任意→retired（管理员） |
| 实例 `instance_status` | `proposed` `active` `paused` `archived` | proposed→active（用户确认）；active⇄paused（用户，或 `LOSS_STREAK_PAUSE` 系统暂停）；任意→archived（用户） |
| 候选信号 `candidate_signal_state` | `open` `drafted` `blocked` `released` `confirmed` `dismissed` `expired` `invalidated` `superseded` | open→drafted/blocked（系统）；blocked→released（系统或手动解除）→drafted/blocked；drafted→confirmed（确认草案）；非终止态→dismissed（用户）/expired/invalidated/superseded（系统） |
| 原因 `reason_status` | `active` `released` `obsolete` | active→released（系统，或 `machine_checkable=false` 时由用户手动）；active→obsolete（所属信号终止） |
| 计划草案 `plan_draft_status` | `pending` `confirmed` `discarded` `expired` `stale` | pending→confirmed/discarded（用户）；pending→expired/stale（系统） |
| 健康度 `health_state` | `published` `observing` | 见 2.8.2；`proposed_action: none \| review \| retire` 只用于提示 |

### 6.1 不可执行原因码（`reason_code`，与 plan.md 2.5.9 一致；`GET /meta/enums` 下发，含默认解除条件）
| code | 默认 `release_condition.kind` | `check_on` | 可手动解除 |
|---|---|---|---|
| `DATA_STALE` | expr | tick | 否 |
| `KEY_DATA_MISSING` | expr | tick, daily_close | 否 |
| `LOW_CONFIDENCE` | expr | tick, daily_close | 否 |
| `NON_TRADING_TIME` | time | schedule | 否 |
| `SUSPENDED` | event | tick, daily_close | 否 |
| `LIMIT_LOCKED` | expr | tick | 否 |
| `ST_OR_DELISTING` | event | daily_close | 否 |
| `NEW_LISTING` | expr | daily_close | 否 |
| `INSUFFICIENT_CASH` | expr | cash_update, import | 否 |
| `T1_NOT_SELLABLE` | time / expr | schedule, holding_change | 否 |
| `NO_POSITION` | expr | holding_change, import | 否 |
| `POSITION_CAP_REACHED` | expr | tick, holding_change | 否 |
| `STRATEGY_BUDGET_EXHAUSTED` | expr | holding_change | 否 |
| `SECTOR_EXPOSURE_EXCEEDED` | expr | holding_change, tick | 否 |
| `REGIME_MISMATCH` | expr | daily_close | 否 |
| `SAME_DIRECTION_PLAN_EXISTS` | event | plan_change | 否 |
| `CONFLICTS_CONFIRMED_PLAN` | user_action | user_action | 是 |
| `BLOCKLISTED` | user_action | user_action | 是（通过 `/restrictions`） |
| `COOLING_OFF` | time | schedule | 否 |
| `LOSS_STREAK_PAUSE` | user_action / time | user_action, schedule | 是 |
| `STRATEGY_CONFLICT` | user_action / expr | user_action, tick | 是 |
| `USER_MUTED` | user_action / time | user_action, schedule | 是（通过 `/restrictions`） |
| `PROFILE_OR_CONSENT_MISSING` | user_action | user_action | 否（完成相应步骤后系统解除） |

---

## 7. 端点
约定：标 🔒 的需要登录且账号已批准；标 🛡 的需要 `role=admin`；标 ⚖ 的还要满足 1.3 的合规门槛；列表接口均按 1.2 分页，除非注明。请求体字段未注明可空的都必填。

### 7.1 认证与账号
| 方法 | 路径 | 说明 | 请求 → 响应 |
|---|---|---|---|
| POST | `/auth/register` | 注册，状态为 `pending` | `{username: string(3–32), password: string(≥10), display_name: string, invite_code: string \| null, agreements: string[]}` → `201 {id, username, status:"pending"}`；可能返回 `409 CONFLICT`、`503 REGISTRATION_CLOSED`、`429 RATE_LIMITED` |
| POST | `/auth/login` | 登录 | `{username, password}` → `200 {user: Me, csrf_token}` + Set-Cookie；可能返回 `401 INVALID_CREDENTIALS`、`403 ACCOUNT_NOT_APPROVED{status, reason?}`、`403 ACCOUNT_LOCKED{retry_after_s}` |
| POST | `/auth/logout` 🔒 | 注销 | → `204` |
| POST | `/auth/password` 🔒 | 修改密码，同时注销其他会话 | `{old_password, new_password}` → `204` |
| GET | `/me` 🔒 | 当前用户 | → `Me {id, username, display_name, role, status, entitlements: {key: value}, consents: {key: {version, accepted_at}}, risk_assessment: {level: int(1–5), assessed_at} \| null}` |
| GET/PUT | `/me/profile` 🔒 | 投资画像（版本化，PUT 生成新版本） | `{horizon_pref: horizon[], effort: "low"\|"medium"\|"high", risk_tolerance: int(1–5), experience: "novice"\|"intermediate"\|"advanced", max_single_position_pct: string(decimal)}` → `{version_no, ...}` |
| POST | `/me/consents` 🔒 | 同意条款 | `{key: "signal_risk_disclosure"\|"privacy"\|"terms", version: string}` → `201` |
| POST | `/me/risk-assessment` 🔒 | 提交风险测评 | `{answers: [{q_id, choice}]}` → `{level, assessed_at}` |
| GET/PATCH | `/admin/users` 🛡 · `/admin/users/{id}` 🛡 | 审核和停用账号 | PATCH `{status: "approved"\|"rejected"\|"disabled", reason: string \| null}` |

### 7.2 账户、成交与导入（只返回掩码字段）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/accounts` 🔒 | 券商账户：`{id, broker_name, alias, shareholder_code_masked, fund_account_masked, created_at}`；POST 只接受 `alias` 和 `broker_name` |
| POST | `/imports` 🔒 | `multipart/form-data`：`file`、`account_id`、`kind: "trades"\|"positions"`。原始文件存放在仓库外、做访问控制的存储中（plan.md 第 3.5 节）→ `201 {batch_id, status:"uploaded"}`；可能返回 `409 IMPORT_DUPLICATE_FILE`、`422 IMPORT_UNRECOGNIZED_FORMAT` |
| GET | `/imports/{batch_id}` 🔒 | `{batch_id, status: import_status, parser, detected_columns: string[], stats: {rows, ok, errors, duplicates}}` |
| GET | `/imports/{batch_id}/rows` 🔒 | 预览行（分页）：`{row_no, status: "ok"\|"error"\|"duplicate", error_code: "IMPORT_ROW_COLUMN_MISMATCH"\|... \| null, normalized: {trade_date, security_code, side, qty, price, amount, fee}}`。**不返回原始行中的股东代码或资金账号**，这类列一律掩码 |
| POST | `/imports/{batch_id}/confirm` 🔒 | 确认导入 → `{status:"confirmed"}`；可能返回 `422 IMPORT_ROW_ERRORS` |
| POST | `/imports/{batch_id}/revert` 🔒 | 回滚 → `{status:"reverted"}` |
| GET/POST | `/trades` 🔒 · `/trades/{id}` 🔒 | 成交列表和手工录入；原记录不可修改，更正时写更正记录 |
| GET | `/snapshots` 🔒 · `/reconciliation` 🔒 | 持仓快照与对账差异 |
| GET | `/portfolio` 🔒 | 持仓汇总：`{cash, total_assets, positions: [{security_code, qty, sellable_qty, cost, market_value, pnl, weight_pct}], exposure: {sector: [{name, pct}]}, DataStatusBlock}` |

### 7.3 自选、行情与证券
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST/DELETE | `/watchlist` 🔒 · `/watchlist/{security_code}` 🔒 | 超出上限返回 `403 ENTITLEMENT_LIMIT_REACHED{key:"watchlist.per_user_cap"}`（上限数值 **待 T003 验证**） |
| PUT | `/watchlist/{security_code}/focus` 🔒 | 设为重点关注 `{focus: boolean}` |
| GET | `/securities?q=` 🔒 | 证券搜索（不分页，最多 20 条） |
| GET | `/quotes?codes=600000.SH,000001.SZ` 🔒 | 只读缓存，**从不触发上游调用**：`{items: [{security_code, price, change_pct, volume, amount, t, DataStatusBlock}]}`；`codes` 最多 200 个 |
| GET | `/securities/{code}/bars?freq=1m\|d\|w&from&to` 🔒 | K 线窗口（每次最多 2,000 根）；缓存里没有时返回 `data_status:"pending"` 并加入回补队列，**不同步等待** |
| GET | `/market/overview` 🔒 | 大盘、宽度、regime、涨跌停统计 |
| GET | `/today` 🔒 ⚖ | 首页聚合：重点关注、待处理草案、原因解除提醒、风险标记 |

### 7.4 策略：L1 卡片、特征白名单、L2 模板与生命周期
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategy-cards` 🔒 | `?completeness=&horizon=&category=`；元素 `{id, key, name, category, horizons, completeness, current_version_no, source_kind, performance: {win_rate_5d: Stat, avg_excess_5d: Stat} \| null}` |
| GET | `/strategy-cards/{id}` 🔒 | 卡片当前版本：2.5.14 B 节的全部字段，加 `field_epistemic`、`narrative`、`gates_missing: string[]`（例如 `["G1:stop_loss_to_quantify"]`） |
| GET | `/strategy-cards/{id}/versions` 🔒 · `/strategy-cards/{id}/versions/{no}` 🔒 | 版本历史，内容不可变 |
| POST | `/strategy-cards` 🔒 | 用户私有卡片（字段同 2.5.14 B 节）→ `201`；可能返回 `422 STRATEGY_INVALID_CONFIG` |
| POST | `/strategy-cards/{id}/versions` 🔒 | 新版本（`base_version_no` 乐观锁）；可能返回 `409 VERSION_CONFLICT` |
| POST | `/strategy-cards/{id}/promotion-requests` 🔒 | 申请晋级，后台跑 G1–G6 → `202 {review_id}` |
| GET | `/promotion-requests/{review_id}` 🔒 | `{decision: "pending"\|"approved"\|"rejected"\|"changes_requested", gate_results: [{gate: "G1".."G7", result: "pass"\|"fail"\|"warn"\|"skipped", detail}], fixture_runs: [{fixture_id, passed, diff}], g6_report: {trigger_rate: Stat, coverage: Stat, max_jaccard: string(decimal), quota_delta_per_min: int}}` |
| GET | `/admin/promotions` 🛡 · POST `/admin/promotions/{review_id}/decision` 🛡 | 审核决定 `{decision, comment}`；G7 文案需通过禁用词校验，否则返回 `422 COMPLIANCE_LINT_FAILED{terms}` |
| GET | `/feature-catalog` 🔒 | 只读，不分页：`[{feature_key, description, dimension, frequency, adjust, unit, warmup_bars, available_at, status: "declared"\|"verified_doc"\|"verified_live"\|"gap"\|"deprecated", epistemic_type}]` |
| GET | `/strategies` 🔒 | L2 模板：`?horizon=&lifecycle=&security_code=`（反查适用的模板）；元素 `{id, key, name, horizons, current_version: {id, version_no, lifecycle}, health: {state, weight: string(decimal), n: int}}` |
| GET | `/strategies/{id}/versions/{vid}` 🔒 | 不可变配置（2.5.14 C 节），加 `lifecycle`、`card_version_id`、`param_hash`、`parent_version_id` |
| POST | `/strategies/{id}/versions/{vid}/derive` 🔒 | 改参派生私有版本 `{param_overrides: object}` → `201 {version_id}`；可能返回 `422 STRATEGY_PARAM_OUT_OF_RANGE{param, min, max}` |
| GET | `/strategies/{id}/versions/{vid}/tracking` 🔒 | 跟踪统计：`{scope: "mine"\|"site", by_horizon: [{horizon_days: 1\|5\|20, win_rate: Stat, avg_return_pct: Stat, avg_excess_pct: Stat, profit_loss_ratio: Stat, max_loss_streak: int}]}` |
| GET | `/strategies/{id}/versions/{vid}/lifecycle-events` 🔒 | 生命周期历史 |
| POST | `/admin/strategies/{id}/versions/{vid}/lifecycle` 🛡 | `{to: lifecycle, reason: string}` → `200 {from, to}`；可能返回 `409 INVALID_STATE_TRANSITION` 或 `422 PROMOTION_GATES_NOT_MET{gates}` |
| GET | `/horizon-assessments?security_code=` 🔒 | 周期分类结果（版本化）：`{suitable: horizon[], scores: {horizon: int}, reasons: [TextWithEvidence], classifier_version}` |

### 7.5 L3 实例、限制与风控
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/strategy-instances` 🔒 | POST `{strategy_version_id, scope: "account"\|"security"\|"watch_group", account_id, security_code: string \| null, horizon, param_overrides: object \| null, fit_ack: {horizon, acknowledged: true} \| null, budget_amount: string(decimal) \| null}` → `201 {id, status:"active", derived_strategy_version_id: uuid \| null, warnings: string[]}`。按 I1–I7 校验，可能返回 `STRATEGY_VERSION_NOT_RUNNABLE`、`CONSENT_REQUIRED`、`STRATEGY_HORIZON_MISMATCH`、`STRATEGY_FIT_ACK_REQUIRED`、`STRATEGY_PARAM_OUT_OF_RANGE`、`ENTITLEMENT_LIMIT_REACHED`、`INSTANCE_SCOPE_INVALID` |
| GET/PATCH | `/strategy-instances/{id}` 🔒 | PATCH `{param_overrides?, budget_amount?}`；改参会生成新的派生版本 |
| POST | `/strategy-instances/{id}/confirm` 🔒 | `proposed → active` |
| POST | `/strategy-instances/{id}/pause` · `/resume` · `/archive` 🔒 | 状态跃迁 |
| GET | `/strategy-instances/{id}/events` 🔒 | 实例事件 |
| GET/POST/DELETE | `/restrictions` 🔒 · `/restrictions/{id}` 🔒 | `{kind: "blocklist"\|"cooling_off"\|"mute", target_type: "security"\|"strategy"\|"instance", target_id: string, until: string(datetime) \| null, reason: string \| null}`。删除后会触发相关原因（`BLOCKLISTED`/`USER_MUTED`）重新检查 |
| GET/PUT | `/risk-controls` 🔒 | `[{control: risk_control, enabled: boolean, params: object, source: "system"\|"user"}]`；可能返回 `422 RISK_CONTROL_INVALID_PARAMS` |
| GET | `/risk-controls/events` 🔒 | 风控事件 |

### 7.6 候选信号、不可执行原因（没有"转计划"接口）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/candidate-signals` 🔒 ⚖ | `?state=&security_code=&instance_id=&horizon=`，排序为 `created_at desc` |
| GET | `/candidate-signals/{id}` 🔒 ⚖ | `CandidateSignal`（见下方示例） |
| GET | `/candidate-signals/{id}/events` 🔒 ⚖ | 状态历史 `[{from, to, cause, at}]` |
| POST | `/candidate-signals/{id}/dismiss` 🔒 | `{note: string \| null}` → `state:"dismissed"` |
| GET | `/non-executable-reasons` 🔒 | `?status=active&signal_id=&code=` |
| GET | `/non-executable-reasons/{id}` 🔒 | `{id, signal_id, code: reason_code, description, evidence: Evidence[], release_condition: ReleaseCondition, status, detected_at, released_at: string \| null, release_evidence: object \| null, released_by: "system" \| "user"}` |
| POST | `/non-executable-reasons/{id}/release` 🔒 | **手动解除**，只允许 `machine_checkable=false` 的原因：`{confirm: true, note: string \| null}`；可机器判断的原因返回 `409 REASON_NOT_MANUALLY_RELEASABLE` |

`CandidateSignal` 示例（数值全部虚构）：
```json
{"id": "00000000-0000-4000-8000-000000000031", "instance_id": "00000000-0000-4000-8000-000000000021",
 "strategy_version_id": "00000000-0000-4000-8000-000000000011", "strategy_key": "demo_trend", "lifecycle": "published",
 "security_code": "600000.SH", "horizon": "swing", "state": "blocked", "proposed_action": "buy", "t_leg": null,
 "score": 70, "confidence": {"level": "medium", "value": 0.55},
 "stops": {"stop_loss": "9.00", "take_profit": null, "time_stop_days": 10},
 "rule_refs": [{"rule_id": "R1", "snippet_id": null, "snippet_version": null, "role": "entry", "dimension": "technical", "passed": true, "value": "10.10", "threshold": "9.90", "evidence_ids": ["E1"]}],
 "evidence": [{"id": "E1", "key": "close", "value": "10.10", "unit": "CNY", "provider": "mairui", "endpoint": "/hsstock/history", "data_as_of": "2026-11-02T15:00:00+08:00", "fetched_at": "2026-11-02T16:40:00+08:00", "epistemic_type": "fact"}],
 "counter_evidence": [{"text": "量比偏低（示例）", "expr": "volume_ratio < 0.5", "evidence_ids": ["E1"]}],
 "invalidation": [{"text": "连续 2 日收于均线下方（示例）", "expr": "close < ma(close, ma_fast) for 2 days", "evidence_ids": ["E1"]}],
 "model_refs": [], "risk_flags": [], "gate_results": [{"gate": "gate_tradability", "passed": true}],
 "reason_ids": ["00000000-0000-4000-8000-000000000041"], "plan_draft_ids": [],
 "valid_until": "2026-11-09T15:00:00+08:00", "snapshot_id": "00000000-0000-4000-8000-000000000051",
 "feature_set_version": "fs_1", "created_at": "2026-11-02T16:45:00+08:00",
 "data_status": "fresh", "data_as_of": "2026-11-02T15:00:00+08:00", "gaps": []}
```

### 7.7 计划草案与计划（确认草案是生成计划的唯一入口）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/plan-drafts` 🔒 ⚖ | 生成草案 `{signal_ids: uuid[](≥1)}` → `201 PlanDraft`。可能返回：没有 passed 的规则引用（只有 model_refs）→ `422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL`；信号状态不是 `drafted`/`released` → `409 INVALID_STATE_TRANSITION`；仍有生效原因 → `409 SIGNAL_NOT_EXECUTABLE{reason_ids}`；信号属于 `simulating` 模板 → `409 STRATEGY_VERSION_NOT_RUNNABLE` |
| GET | `/plan-drafts` 🔒 · `/plan-drafts/{id}` 🔒 | `PlanDraft {id, status: plan_draft_status, signal_ids, action, qty_range: {min, max, lot}, price_range: {low, high}, stops, max_loss_amount, max_loss_pct, fee_estimate: {amount, epistemic_type}, user_context_snapshot: {holding_qty, sellable_qty, cash, sector_pct}, risk_flags: RiskFlag[], judgment_checklist: [{id, question, required: boolean}], valid_until, market_rule_version_id}`，其中金额都是 `string(decimal)` |
| POST | `/plan-drafts/{id}/confirm` 🔒 ⚖ | `{checklist_answers: [{id, answer: "yes"\|"no"\|"unsure", note?}], risk_ack: true, chosen_qty: string(decimal), chosen_price: string(decimal), deviation_ack: boolean}` → `201 {plan_id, plan_version_no: 1}`。可能返回：必答项缺失 → `422 CHECKLIST_INCOMPLETE{missing}`；`risk_ack` 不为 true → `422 RISK_ACK_REQUIRED`；数量或价格超出区间且未确认偏离 → `422 DEVIATION_ACK_REQUIRED{fields}`；草案状态为 stale/expired → `409 PLAN_DRAFT_STALE` |
| POST | `/plan-drafts/{id}/discard` 🔒 | `{note}` → `status:"discarded"` |
| GET/POST | `/plans` 🔒 · `/plans/{id}` 🔒 | 操作计划；POST 只用于用户**手工**创建（`origin:"manual"`），不能引用候选信号 |
| POST | `/plans/{id}/versions` 🔒 | 修改计划，生成新版本（`base_version_no` 乐观锁） |
| POST | `/plans/{id}/close` 🔒 | `{status: "done"\|"cancelled", note}`；会触发 `SAME_DIRECTION_PLAN_EXISTS` 的解除检查 |

### 7.8 建议卡、日报、提醒、复盘、通知
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/suggestions` 🔒 ⚖ · `/suggestions/{id}` 🔒 ⚖ | 候选信号汇总卡（plan.md 2.5.5 的 JSON 视图，内容不可变）；`/suggestions/{id}/chain` 返回取代链 |
| POST | `/suggestions/{id}/actions` 🔒 | `{kind: "viewed"\|"dismissed"\|"acted_trade_linked", trade_id: uuid \| null, note}`。**没有 `converted_to_plan`**；`draft_requested`、`draft_confirmed`、`reason_manually_released` 由服务端在相应接口里自动写入 |
| POST | `/suggestions/refresh` 🔒 ⚖ | `{security_code}`，只读缓存重算；可能返回 `409 SUGGESTION_REFRESH_TOO_FREQUENT` |
| GET | `/suggestions/{id}/tracking` 🔒 | `{t1: Stat, t5: Stat, t20: Stat}`，并附各期的价格依据 |
| GET | `/daily-reports` 🔒 ⚖ · `/daily-reports/{date}` 🔒 ⚖ | 盘后日报（不可变） |
| GET | `/signals` 🔒 ⚖ | 盘中事件流（规则事件，不含动作建议） |
| GET/POST/PATCH/DELETE | `/alert-rules` 🔒 · `/alerts` 🔒 | 提醒规则与触发记录 |
| GET/POST | `/reviews` 🔒 · `/reviews/{id}` 🔒 | 复盘 |
| GET | `/notifications` 🔒 · `/notifications/unread-count` 🔒 · POST `/notifications/{id}/read` 🔒 | 通知中心 |
| GET/PUT | `/notification-preferences` 🔒 · `/channels` 🔒 | 渠道与免打扰设置 |

### 7.9 管理端（🛡；普通用户访问 `/admin/evaluation/*` 返回 404，不暴露其存在）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/ingest/status` 🛡 | 只读：`{leader: {instance_id, egress_ip_masked: "203.0.113.x", lease_expires_at}, budget: {per_minute_limit: int, used_last_minute: int}, queues: [{priority: "p0_intraday"\|"p1_daily"\|"p2_backfill", depth: int, oldest_age_s: int}], errors_24h: [{upstream_code: string, count: int}], ip_limit_alerts_24h: int, freshness: [{dataset, data_as_of, data_status}], licence: {expires_on: string(date), days_left: int}}`。**不返回 licence 内容**；`per_minute_limit` 等数值 **待 T003 验证** |
| POST | `/admin/ingest/pause` · `/admin/ingest/resume` 🛡 | 暂停或恢复外呼（迁移和冷备切换时使用，写审计） |
| GET/PUT | `/admin/realtime-settings` 🛡 | 刷新间隔、分层上限（默认值 **待 T003 验证**） |
| GET/POST/PATCH | `/admin/llm/providers` · `/admin/llm/models` · `/admin/llm/routes` · `/admin/llm/prompts` 🛡；POST `/admin/llm/test`；GET `/admin/llm/usage` | API key 只写不读（响应返回 `api_key_set: true`） |
| GET/POST/PATCH | `/admin/plans` · `/admin/subscriptions` 🛡 | 套餐与权益（不接支付） |
| GET/POST | `/admin/evaluation/runs` 🛡 · GET `/admin/evaluation/runs/{id}` 🛡 | 问题 26 获批后才启用，未启用时返回 `404`。POST `{kind: "factor_ic"\|"event_study"\|"param_robustness"\|"daily_revalidation", target: {strategy_version_id? , feature_key?}, data_range: {from, to}, params: object}` → `202 {run_id}`；结果中 `metrics` 的每一项都是 `Stat` |
| GET | `/admin/audit-logs` 🛡 | 审计 |

### 7.10 元数据与健康
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/meta/enums` | 第 3 节全部枚举、6.1 原因码表（含默认解除条件）、错误码列表（不分页，可缓存） |
| GET | `/health` | `{status: "ok"\|"degraded", db: "ok", redis: "ok", ingest: "ok"\|"stale"\|"paused"}`，不需要登录、不含细节 |

---

## 8. SSE `GET /stream` 🔒
- `text/event-stream`；每 15 秒发一次 `heartbeat`；支持 `Last-Event-ID` 续传，服务端保留最近 10 分钟的事件；断线时客户端退回到轮询 `/notifications/unread-count`。
- 每个事件：`id: <单调递增字符串>`，`event: <type>`，`data: <JSON>`。

| event | data | 说明 |
|---|---|---|
| `heartbeat` | `{at}` | |
| `quote` | `{items: [{security_code, price, change_pct, t}], data_as_of}` | 只推送用户自选或持仓的证券，来自缓存 |
| `signal` | `{signal_event_id, security_code, kind, at}` | 盘中规则事件 |
| `candidate_signal` | `{id, security_code, state, proposed_action, strategy_key}` | ⚖ 候选信号新建或状态变化 |
| `reason_released` | `{reason_id, signal_id, code, released_at}` | ⚖ 原因已解除，系统正在重新检查 |
| `plan_draft_ready` | `{plan_draft_id, signal_ids, security_code, valid_until}` | ⚖ 生成了新的草案，等待确认 |
| `plan_triggered` | `{plan_id, condition, at}` | 提示"您的计划条件已满足"，**不下单** |
| `suggestion` | `{id, security_code, supersedes_id}` | ⚖ |
| `notification` | `{id, kind: notification_kind, severity, title}` | |
| `report` | `{date}` | 日报已生成 |
| `data_status` | `{dataset, data_status, data_as_of}` | 数据变旧或恢复（例如采集暂停） |

---

## 9. 契约测试要点（T-T17 等）
- 所有响应示例都能用 OpenAPI schema 校验通过；所有统计字段都带 `n`，缺少即失败。
- 候选信号和建议的响应中，P1 要求的四个数组都非空，`model_refs[*].role == "auxiliary"`。
- 不存在任何 `POST /candidate-signals/{id}/convert` 一类的接口；只有 `/plan-drafts/{id}/confirm` 能创建 `origin=plan_draft` 的计划。
- 普通用户访问 `/admin/evaluation/*` 返回 404，访问其他 `/admin/*` 返回 403。
- 任何响应、日志和错误信息中都不出现 licence、原始股东代码或资金账号（用虚构 fixture 做扫描）。
- 行情类接口在采集服务暂停时返回 `data_status:"stale"`，而不是 5xx，也不会触发上游调用。
