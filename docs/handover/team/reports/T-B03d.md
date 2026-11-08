# T-B03d 评审修复（按契约 v0.2.8 正式文本对齐）— commit **116cb7e**

来源：`reports/review-T-B03a-B03b-B04a-B16-B45.md` 的裁定 + 契约 v0.2.8（T-A09，docs 6ef79c4）#11–#14。
基于 T-B02y v0.2.8 同步提交 457a211。不调用麦蕊（容器与测试都去掉了 MAIRUI_LICENCE），STOP 文件 sha256 不变，没有 push。

## 裁定
| 项 | 处理 |
|---|---|
| (a) `/admin/*` 不进 openapi.json | 维持，不改（自检断言 openapi 不含 `/api/v1/admin/data-licences`） |
| (b) 22 个原因码 | 维持，不改 |
| (c) 注册蜜罐 | 按 v0.2.8 §7.1 / #11 实现，见下 |
| (d) 暂停中 PUT | 202 `paused_by_admin`，不验证；只有管理员 resume 能解除 |

## 改动
**注册蜜罐（#11，`app/api/v1/auth.py`）**
- `RegisterIn` 加 `website: string | null`（内容和长度都不校验，strip 后非空就算命中）和 `form_started_at: int | null`（StrictInt，不是整数 → 400；未传就不做时间检查）。时间判定：`now_ms - form_started_at < 3000`（包括未来时间）→ `too_fast`。
- 判定顺序：closed → 503；IP 限速（命中的请求也计数）；字段 + 邀请码 → 400；用户名冲突 → 409；待审核上限 → 503；最后是蜜罐。邀请码兑换、409 和待审核上限都在同一事务的保存点里检查，命中时回滚保存点，所以邀请码不被消耗。
- 命中时返回同样的 201 `{随机 uuid, 归一化用户名, "pending"}`，不建用户；审计 `auth.register_honeypot`：actor 为 null，照常写 ip_hash，detail 只有 `{trigger: website|too_fast|both}`（不含用户名、申请说明、website 内容）。

**M1 暂停按用户（#12/#14）**
- 新表 `app.user_data_licence_holds(user_id PK/FK, paused_at)`，迁移 **0010**；从现有 `status='paused_by_admin'` 的证书行回填；downgrade 删表。
- pause：写暂停记录，同时把证书行设为 paused_by_admin。用户 DELETE 证书后暂停记录仍在：GET 和 `/me` 都显示 `paused_by_admin`（证书字段为 null），`/test` 返回 409 `DATA_LICENCE_UNAVAILABLE{status:"paused_by_admin"}`，再 PUT 新行仍是 paused_by_admin，不投递验证。
- resume：删除暂停记录；有证书 → pending_verification 并投递；没有证书 → 204，GET 返回 `not_set`。
- 管理端列表外连暂停表，没有证书的暂停用户也显示 paused_by_admin（`licence_id` 为 null）。

**M2 / #13 重复 PUT 同一证书**
- 判断是否同一证书：HMAC 相同。若 `paused_until` 未到期，或状态是 `quota_exceeded`/`ip_limited`，就保留原状态、`paused_until` 和 `licence_id`，返回 202 + 当前状态，不验证，只更新 tier/has_quant_pro/expires_on。
- 暂停中重复 PUT 同一证书也走这条原地更新。
- 其他情况照旧：换新行 → pending + 验证。

**(d)**：暂停中 PUT 任何证书都返回 202 paused_by_admin，不做验证。

**M5 改密**：先检查限速（`RateLimiter.ensure_not_limited`），超限直接 429 + Retry-After，不验证旧口令；旧口令错误再计数。

**M4 开关** `DATA_LICENCE_SETTINGS_ENABLED`（`Settings.licence_settings_enabled`）：未设置时，`APP_ENV=production` 默认**关闭**，其余环境开启。关闭时 PUT/PATCH/test 返回 503 `MAINTENANCE`，GET/DELETE 照常（用户仍能删除证书）。

**同提交内的 v0.2.8 同步项**（和上面改的是同一批文件，所以并入本提交）：`AdminDataLicence.licence_id`（#2），以及 `service.ingest_licences()`（#1，见 T-B02y.md）。

## 自检（隔离库 be-b03a-pg / be-b03a-redis，虚构证书）
`/tmp/tb02/selftest_tb03d.py` **67/67 PASS**：
- 蜜罐：website、too_fast、未来时间、both；只有空白的 website 正常注册；不传时间正常注册；超长 website 也只算命中；`"123"`/1.5/true → 400；未知字段 400；409、400、503 待审核上限、closed 503 都先于蜜罐；命中计入 IP 限速（2 次命中后正常注册 429）；invite 模式命中不消耗邀请码、随后同一码正常注册成功；审计 detail 只有 {trigger}；openapi 含两个新字段。
- M5：超限后用正确旧口令也 429，口令未改。
- M1/(d)/#14：暂停中 PUT 同一证书原地更新（licence_id 不变）、PUT 新证书 paused、DELETE 后 GET 和 `/me` 都是 paused、test 409、管理端列表显示 paused 且 licence_id null、再 PUT 仍 paused 且不投递、resume 后 pending + 投递、证书已删时 resume → not_set、未设置证书 pause → 409 不写记录。
- M2/#13：quota_exceeded 加未到期 paused_until 时保留状态与 paused_until、licence_id 不变、只改 tier；ip_limited（paused_until 已过或为空）保留；冷却中换新证书 → pending；active 重复 PUT → 照常新行验证。
- M4：dev 默认开、production 默认关、显式 true 开、环境变量生效；关闭时 PUT/PATCH/test 503 MAINTENANCE，GET/DELETE 可用。
- #1/#2：ingest licences[] 键集合、排序、not_set 不列、daily_limit、与管理端列表 licence_id/calls_today/queue_depth 一致、不泄露证书值子串/密文/HMAC。
- 迁移 0010：downgrade 删表；upgrade 只回填暂停中的用户；`alembic check` 无差异。

回归：tb03a（39，已改为 M5 下 429、RegisterIn 含蜜罐字段）、tb45 67（AdminDataLicence 含 licence_id）、tb03c 57、api 205、tb16 123、xff、t006e、env、tb04ax、tb02x、tb02y 86 全过；ruff / mypy（74 文件）通过。测试员套件结果见 T-B02y.md（5 个失败都是测试侧还停在 v0.2.7）。

## 剩余风险
- 冷却中先 DELETE 再 PUT 同一证书：删除时 HMAC 已抹掉，无法识别是同一证书，会重新验证。PUT 每小时 10 次的限速可以缓解；建议 ingest 的熔断按 HMAC 记录冷却。
- too_fast 依赖客户端时钟；契约要求前端用 `/meta/registration` 的 Date 头校正。
- M3 已由 T-O10 处理，本任务未改。

## 需要谁做什么
- **运维**：执行迁移 **0010**；生产默认关闭证书设置。确认上线时设 `DATA_LICENCE_SETTINGS_ENABLED=true`（未设置时生产环境 PUT/PATCH/test 返回 503）。
- **前端**：注册表单加隐藏字段 `website` 和 `form_started_at`（用服务器时钟校正后的毫秒值）；暂停期间证书页按 paused_by_admin 显示（即使证书已删除）。
- **测试员**：补 v0.2.8 #11–#14 用例；`/auth/password` 超限后用正确旧口令也应 429。
- **ingest（T-B04x）**：熔断/冷却建议按 licence HMAC 记录。
