# 裁定：T-O11 未执行的“aia_deny 清单补上 §1 的全部列”

- 评审人：项目架构师
- 时间：2026-11-01 20:35 MST（America/Denver）
- 性质：只写报告，没有改 plan，没有改仓库。

## 结论

1. 这条指令里的“aia_deny”指的是 **aia_maint 不可读的列清单**，不是 grants.sql 里只作用于 aia_api 的 `aia_deny` 数组。
2. 运维在 7f3f9ba 里已经用 `maint_deny` 落实了这个意思，所以**这一项按“已完成”关闭**。
3. **aia_api 的 deny 保持现状，只拒绝 licence 密文。** 不要把 §1 的列加给 aia_api。

## 原文与出处

| 出处 | 内容 |
|---|---|
| plan.md:3101（7.3 第 7 条，e56462c） | aia_maint 的列权限原则：不能 SELECT 密文和 password_hash，也不授予 UPDATE |
| plan.md:3102（7.3 第 8 条） | worker 改用 aia_api，只给 DML；第 ③ 点：aia_api 仍然不能读 licence 密文 |
| plan.md:3100（7.3 第 6 条，47c4b9c） | 角色成员关系：aia_api、aia_ingest 都不是 aia_maint 的成员 |
| aia_maint-grants.md §1（5–14 行） | aia_maint 不能 SELECT 的列：<br>· users.password_hash；<br>· user_data_licences.ciphertext、licence_hmac；<br>· llm_providers.api_key_ciphertext；<br>· notification_channel_bindings.target_ciphertext；<br>· import_rows.raw_line；<br>· llm_calls.request_body、response_body；<br>· user_data_licence_cooldowns.fingerprint |
| aia_maint-grants.md §7:297 | 原文：“运维：用 §3 替换 grants.sql 的 `$maint` 块…，**aia_deny 清单补上 §1 的全部列**；部署后跑 §4。” |
| T-O11.md:348 | 运维没有把这些列加进 aia_api 的 deny，原因是 aia_api 读不到 password_hash 会导致登录失效。运维改为把它们放进 aia_maint 的拒绝断言，并请架构师裁定。 |
| grants.sql:86 | `aia_deny text[] := ARRAY['app.user_data_licences.ciphertext'];` 只作用于 aia_api（约 105–138 行）。 |
| grants.sql:16 | 注释写“两处 aia_deny 数组保持一致”，但现在只有一处，注释已过时。 |
| grants.sql:349–354、443–452 | aia_maint 的 `maint_deny` 清单及自检 |

**歧义的来源**：§7 写的时候，grants.sql 里唯一叫 `aia_deny` 的数组属于 aia_api，但 §1 的标题和上下文讲的都是 aia_maint。

## 如果照字面执行，登录为什么会失效

- 应用里有多处 `select(users)`。SQLAlchemy 会把表的全部列逐个写进 SELECT，包括 password_hash。
- 在 PG 的列级授权下，只要其中一列没有 SELECT 权限，整条查询就会报错。
- 受影响的代码行，按 plan 7.3 第 8 条，worker 也用 aia_api：

| 表.列 | 代码位置 | 后果 |
|---|---|---|
| users.password_hash | app/auth/service.py:31，按 username 执行 `select(users)` | 登录失败 |
| users.password_hash | app/auth/deps.py:138，按 id 执行 `select(users)` | **每个已认证请求**都失败 |
| users.password_hash | app/api/v1/auth.py:335、393、445（改密码、校验密码等） | 对应接口失败 |
| user_data_licences.licence_hmac | app/licences/service.py:223、248、474 | 证书去重、绑定失败 |
| user_data_licence_cooldowns.fingerprint | app/licences/service.py:323 | 冷却判定失败 |
| import_rows.raw_line | app/api/v1/imports.py:567、873（解密原始行） | 导入预览、错误行功能失败 |
| llm_providers.api_key_ciphertext、notification_channel_bindings.target_ciphertext | 目前只有表定义（llm.py:39、notify.py:65），代码里还没有读取方 | 现在不坏。但 plan 的主密钥表（e56462c）写明由 api 处理“LLM 密钥密文”，以后一定会坏。 |

**实测**：在库 m749 里开一个事务，最后 ROLLBACK。
1. 撤销 aia_api 对 users 的表级 SELECT，只授予除 password_hash 以外的所有列。
2. 以 aia_api 身份执行 15 列的 select，报 `ERROR: permission denied for table users`。
3. 同一身份下 `SELECT id, username` 成功。

## 原意想防什么

- aia_maint 是运维 CLI 和维护用的凭据，会被人手直接拿来用。
- 原意是：这类凭据即使泄露或被误用，也拿不到口令哈希、各类密文和原始导入行。
- 这样维护通道与持有主密钥的应用通道分开，读到的密文也无法和应用侧的密钥合在一起使用。
- aia_api 本身持有 APP_MASTER_KEY，就是这些数据的合法使用方。对它禁止读这些列不会带来任何隔离效果，只会把功能弄坏。
- 唯一的例外是 licence 密文：它由 ingest 用私钥解密，api 只有公钥。所以 aia_api 不能读 licence 密文（7.3 第 8 条 ③、T-B45），这一条有实际意义，而且已经落实。

## 最小替代方案（不改权限模型）

1. **后端改 §7 措辞（文档）**：把“aia_deny 清单”改成“aia_maint 的列拒绝清单（grants.sql `maint_deny`）”，并注明“aia_api 的 `aia_deny` 只放 licence 密文，不扩展”。
2. **运维改 grants.sql:16 的过时注释**：改为“aia_api 的 `aia_deny` 与 aia_maint 的 `maint_deny` 是两份不同的清单，前者只放 licence 密文”。
3. **运维在 verify-roles.sh 补行为断言**（127–157 行一段）：对 aia_maint 加 `expect_denied`，覆盖三列：
   - `notification_channel_bindings.target_ciphertext`；
   - `llm_calls.response_body`；
   - `user_data_licence_cooldowns.fingerprint`。

   目前这三列只有目录级的检查，没有行为检查。
4. **不建议**对 aia_api 拒绝 api_key_ciphertext 或 target_ciphertext：plan 要求 api 自己解密 LLM 密钥和通知目标。

## 谁做什么

- **后端**：第 1 项（改 plan 措辞需要架构师确认后才提交）。
- **运维**：第 2、3 项，改完后跑 verify-roles，预期在 54 项基础上加 3 项。
- **架构师**：在 T-O11 上标注“按本裁定关闭”。
