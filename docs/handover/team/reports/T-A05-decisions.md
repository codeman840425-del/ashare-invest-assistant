# T-A05 定夺：上传上限键名、IT0C、后端三项取舍、auth.yaml

- 架构师；2026-11-01；提交 **7c62f59**（只改 docs/plan.md、docs/api-contract.md；用 pathspec 提交；gitleaks 无发现；未 push）
- 配套评审：review-T-B02a.md（通过）、review-T-B03.md（有条件通过）

## (a) 导入上限：新建 `config/imports.yaml`，键路径为 `imports.*`
- **结论**：不沿用后端的 `ingest.imports.max_file_bytes`，最终键名定为 **`imports.max_file_bytes`**。
- **理由**：plan 6.1 规定 `ingest.yaml`"只有 ingest 进程读取"，而 ingest 是持有 licence、相互隔离的采集服务。上传上限由 api 与 worker 使用，放进 ingest.yaml 会让 api 读取采集配置，打破隔离。现在只改动 3 处引用，迁移成本低。
- 键与默认值：
  - `schema_version: 1`
  - `max_file_bytes: 5242880`
  - `max_files_per_upload: 5`
  - `max_request_bytes: 27262976`（= nginx 26m，且必须大于 file × count）
  - `max_rows_per_file: 50000`
  - `allowed_extensions: [".txt", ".csv"]`
  - `raw_file_retention_days: 365`
- 不可热调，环境变量不能覆盖。存储路径只来自环境变量 `IMPORT_STORAGE_PATH`，YAML 中不设路径键。
- 契约改动：changelog #22 与 §4 的 413 行统一引用 `imports.max_file_bytes`；`max_bytes` = `imports.max_request_bytes`。

## (b) IT0C 与 reason_code 的冲突：不新增原因码
- `SH0C`/`IT0C` 是 `horizon_classifier.yaml` 的规则 ID，只出现在 `HorizonCap.rule_id`（`kind: "requires"`）。它们只降低周期适配分，不阻断信号或计划，所以**不是** reason_code，也不进 `/meta/enums`。§6.1 仍为 23 个原因码，`requires` 的语义不变。
- 改动内容：
  - 契约：HorizonCap 补一句说明；测试点新增 IT0C 示例（novice 夹具 `intraday_t ≤ 59`，caps 含 IT0C），并断言它不在 reason_codes 中；记为 changelog v0.2.3 同日补充 #23。
  - plan：在 L537 附近补同样的说明。

## (c) 后端三项取舍
| 项 | 判定 | 说明 |
|---|---|---|
| 用户名 4–32 | **采纳** | 与 plan 3.3/3.6 一致，契约从 3–32 改为 4–32（#24） |
| invite 模式返回 503 | **过渡期采纳** | 邀请码功能（T-B03c）完成前，invite 按 closed 处理。正式行为（#27）：invite 模式下 `invite_code` 与 `apply_note` 必填；邀请码不存在/过期/已用/已吊销/用户名不符时，一律返回 `400 VALIDATION_ERROR {field: invite_code, issue: invalid}`，不新增错误码 |
| consent doc_version 'unversioned' | **有条件采纳** | 只允许在 closed 模式下存在。版本取自 `auth.yaml consents.doc_versions`，null 记为 "unversioned"；`REGISTRATION_MODE=invite` 时若任一版本为 null，启动失败；`POST /me/consents` 只接受当前版本，否则返回 400；`GET /meta/registration` 返回 `doc_versions`；key 新增 `sensitive_financial_info`，且写入账户、导入、手工录入数据前要求已同意（#26） |

## (d) 新建 `config/auth.yaml`
- **为什么单独成文件**：现有文件都按服务或领域划分，认证参数不属于其中任何一个；而且 `auth.yaml` 只给 api 读取。
- `REGISTRATION_MODE` 仍是环境变量，不放进 YAML。
- 定义定夺后共有 **8 个 business 文件**。

**password**
- `min_len: 10`，`max_len: 128`

**password_hash（argon2id）**
| 键 | 默认值 | 下限 |
|---|---|---|
| `memory_kib` | 65536 | ≥ 19456 |
| `time_cost` | 3 | ≥ 2 |
| `parallelism` | 1 | ≥ 1 |
| `hash_len` | 32 | ≥ 16 |
| `salt_len` | 16 | ≥ 16 |
- 参数低于下限时启动失败；登录成功后旧哈希透明升级为新参数。

**session**
- `idle_ttl_s: 604800`（7 天滑动）
- `absolute_ttl_s: 2592000`（30 天，不续期）
- `remember_me: false`（V1 固定为 false）
- 会话轮换：登录和改密时轮换 sid 与 csrf；改角色、禁用、驳回、重置密码时吊销该用户全部会话。
- Cookie：`Max-Age = absolute_ttl_s`；Secure=false 在非 local/test 环境启动失败。

**invite**
- `code_bytes: 16`（128 bit）
- `default_ttl_h: 168`
- `max_ttl_h: 720`
- `max_uses: 1`
- 编码与存储：Crockford Base32 编码，26 字符，4 位一组；入库只存 `HMAC-SHA256(APP_MASTER_KEY)`，明文只在创建时显示一次。
- 用法规则：
  - 只由管理员发放；
  - 可选绑定用户名，不绑定邮箱（V1 不验证邮箱）；
  - 可以吊销；
  - 核验邀请码与建用户放在同一事务内；
  - 发放、吊销、使用都写审计。
- 数据表：`invite_codes`（plan 3.3）。

**consents**
- `doc_versions`：五类文书默认都是 null。

**契约改动**
- §1.3 会话规则
- §7.1：注册（`apply_note`、`agreements` 恰为 3 项、密码长度 10–128）；改密（轮换会话）
- §7.9：`GET/POST /admin/invites`、`DELETE /admin/invites/{id}`
- 测试点
- 新增任务：T-B03c 邀请码（依赖 T-B03b，invite 模式启用前必须完成）

## 谁做什么
**后端**
- T-B03 后续提交（M2–M4、S3、S6）：
  - 迁移 `imports.*`，删除 ingest.yaml 中的 imports 注释块；
  - 新建 imports.yaml、auth.yaml 及其模型（含下限校验）；
  - 会话加绝对过期，改密时轮换会话；
  - consents 加入版本校验与 `sensitive_financial_info` 门槛；
  - `/meta/registration` 返回 `doc_versions`。
- T-B03a：
  - 可信代理列表 `TRUSTED_PROXIES`（M1 后端部分）；
  - 按 `username_tried` 锁定并做 dummy 哈希；
  - 旧密码校验限速。
- T-B03c：邀请码功能。

**运维**
- nginx 两个 location 都加 `proxy_set_header X-Real-IP $remote_addr;`（M1，对外暴露前必须上线）。
- CI 校验 nginx 的 `client_max_body_size` 与 `imports.max_request_bytes` 一致。

**前端**
- 注册：用户名最少 4 位，增加申请说明 `apply_note`。
- 改密 204 之后从 Cookie 重新读取 CSRF 令牌。
- 导入前弹出 `sensitive_financial_info` 单独同意；提交 `doc_versions` 中的版本。
- caps 按 `rule_id` 展示。
- 新增管理端邀请码页（等 T-B03c）。

**测试**
- 按契约 #23–#27 补用例。
- 补 X-Real-IP 伪造用例。
- 白名单文件数改为 8。

## 待决问题
1. 风险测评问卷（T-B15）上线之前，所有 ⚖ 接口都会恒返回 CONSENT_REQUIRED。本人自用阶段，是否用 CLI 写入一条测评记录来过渡？需要编排者或用户决定。
2. 五类文书的正式版本号和文本由谁出、什么时候出？这是切换到 invite 模式的前置条件，且需要律师意见（plan 第 9 节问题 1）。
3. `absolute_ttl_s` 30 天是工程默认值（◇），用户可以改。
4. `TRUSTED_PROXIES` 默认网段取决于 compose 网络定义，需要运维确认。


## 后续（T-A05，35f4880）
- 待决问题 1（CLI 写测评的过渡方案）：已关闭，编排者定不做，后端按研究员问卷直接实现（plan §9 问题 41）。
- 待决问题 2（文书版本）：已关闭，研究员起草，用户审阅后才对第三方开放，closed 阶段允许 unversioned；版本来源改为 legal_documents 表，auth.yaml consents.doc_versions 作废（plan §9 问题 42、3.6）。
- 注册 agreements 的 risk_disclosure 改为 signal_risk_disclosure（契约 v0.2.4 #2）。
