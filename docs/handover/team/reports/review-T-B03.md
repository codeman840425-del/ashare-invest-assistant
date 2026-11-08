# 评审：T-B03（f44b6ee）认证与同意

- 评审人：架构师；日期：2026-11-01
- 依据：plan 3.3 / 3.6 / 7.3 / 第 9 节问题 18；api-contract v0.2.3 §1.3 / §4 / §7.1；T-A05 定夺（7c62f59）
- 结论：**有条件通过**。可以合入，用户本人在 `closed` 模式下使用。但 M1–M4 必须在 T-B03a 合入前修完，M1 还必须在任何对外暴露之前修完；`invite` 模式另需 T-B03c 完成。
- 级别计数：阻断 0 / 主要 4 / 次要 7 / 建议 4

## 1. 验证方式
- ruff、format、mypy 全部干净；测试 513 passed / 89 skipped / 0 failed；Alembic 往返正常。
- 实测：uvicorn + PG + Redis 临时容器，`REGISTRATION_MODE=open`，`SESSION_COOKIE_SECURE=false`，只在本地测。

## 2. 安全检查清单
| 项 | 结果 | 证据 |
|---|---|---|
| 密码哈希 | ✅ argon2id，m=64MiB / t=3 / p=1（passwords.py:18–20），登录时 rehash；⚠ 参数写死成常量（M4） | |
| Cookie 属性 | ✅ `sid; HttpOnly; Max-Age=604800; Path=/; SameSite=lax`，Secure 来自配置；`csrf_token` 不设 HttpOnly | 实测 Set-Cookie |
| CSRF | ✅ 令牌存在会话里，`hmac.compare_digest`，所有非安全方法都校验；缺失或错误 → 403 CSRF_FAILED；login 只接受 JSON（text/plain、表单 → 400），挡住了简单表单的 login-CSRF | 实测 |
| 锁定 | ⚠ 已检查 `locked_until`（auth.py:197–199），但还没有任何地方写入它（属 T-B03a）；锁定分支跳过哈希计算（S1） | |
| INVALID_CREDENTIALS 不泄露 | ✅ 用户不存在与密码错误返回同一个 401 响应体；403 状态类错误只在密码正确之后出现 | 实测 |
| 时序 | ✅ 用户不存在时对 `_DUMMY_HASH` 做一次校验（passwords.py:62），两种情况耗时都约 0.16 s | 实测 |
| 邀请流程 | ⏸ 非 open 模式一律返回 503（auth.py:117–118）；T-A05 认可作为过渡，正式实现见 T-B03c | |
| 默认关闭注册 | ✅ `registration_mode` 默认 CLOSED（config.py:348） | |
| 审计 | ✅ register / login / login_failed / profile / consent / logout 都有记录，ip_hash 为 HMAC；⚠ IP 来源可被伪造（M1）；锁定与未批准分支没有审计（S2） | 实测 audit_logs |
| 日志无秘密 | ✅ 日志里没有密码、sid、CSRF 值 | 实测 grep |
| 会话固定 | ✅ 登录时作废 Cookie 中的旧会话，sid 用 `token_urlsafe(32)`，Redis 只存摘要 | |
| 改密 | ✅ 其他会话立即 401；⚠ 当前会话没有轮换（S3） | 实测 |

## 3. 发现
| # | 级别 | 位置 | 问题 | 修改 |
|---|---|---|---|---|
| M1 | 主要 | app/auth/deps.py:54–60；deploy/nginx/nginx.conf:44–50、66–72 | `client_ip` 无条件信任 `X-Real-IP`，但 nginx 只设置了 X-Forwarded-For、**没有设置 X-Real-IP**，客户端自带的头会原样转发。实测带上 `X-Real-IP: <host>` 后审计 ip_hash 随之改变。审计完整性因此已被破坏，T-B03a 的按 IP 限速也会被绕过 | 运维：两个 location 都加 `proxy_set_header X-Real-IP $remote_addr;`。后端：新增 `TRUSTED_PROXIES`（CIDR 列表，默认为 compose 网段），只在直连地址属于可信代理时才读 X-Real-IP，否则用 `request.client.host`。测试：从不可信来源带伪造头，ip_hash 不变 |
| M2 | 主要 | app/api/v1/me.py:55–57、142 | `POST /me/consents` 接受任意 `version` 字符串（实测 "anything-goes" → 201），同意记录失去合规证明力 | 按 T-A05：版本取自 `auth.yaml consents.doc_versions`（null → "unversioned"），不一致 → 400 VALIDATION_ERROR `field: version`；`GET /meta/registration` 返回 `doc_versions`；注册时 `agreements` 也按当前版本记录 |
| M3 | 主要 | app/api/v1/me.py:56；consents.py | `key` 没有 `sensitive_financial_info`，plan 7.3（个保法第 28 条）要求的单独同意无法完成；导入接口也没有门槛（契约 v0.2.3 #26 已补） | `key` 加 `sensitive_financial_info`（DB kind 已在 CHECK 内）；`POST /accounts`、`POST /imports`、手工录入写接口依赖一个 `require_consent("sensitive_financial_info")` → 403 CONSENT_REQUIRED |
| M4 | 主要 | app/auth/sessions.py:25、52、99–100；app/auth/passwords.py:18–29 | 只有空闲 7 天滑动过期，**没有绝对过期**，持续使用的会话可以永不过期；argon2 参数和 TTL 写死成常量，plan 要求"可配置" | 按 plan 6.1 新建 `config/auth.yaml`（session.idle_ttl_s / absolute_ttl_s、password_hash.*，带 OWASP 下限校验）；会话 JSON 已有 `created_at`，在 touch 时检查 `now - created_at > absolute_ttl_s` 就作废；Cookie Max-Age 改为 absolute_ttl_s |
| S1 | 次要 | app/api/v1/auth.py:197–199 | 锁定检查放在校验密码之前且跳过哈希计算：被锁账号响应更快，并暴露该用户名存在。目前 `locked_until` 不会被写入，所以影响为 0 | T-B03a：按 `username_tried` 锁定（不存在的用户名同样计数），锁定分支也做一次 dummy 校验 |
| S2 | 次要 | app/api/v1/auth.py:197–228 | ACCOUNT_LOCKED、ACCOUNT_NOT_APPROVED 分支不写审计 | 写 `login_failed`，detail `{reason: "locked"\|"not_approved"}` |
| S3 | 次要 | app/api/v1/auth.py:274–305 | 改密后不轮换当前会话（契约 v0.2.3 #25 已要求轮换） | 作废当前会话，新建会话并下发新的 `sid` 和 `csrf_token` Cookie，仍返回 204 |
| S4 | 次要 | app/api/v1/auth.py:282–283 | 旧密码校验没有限速，可以借已登录会话爆破旧密码 | 纳入 T-B03a 限速，按 user_id 计数 |
| S5 | 次要 | app/auth/sessions.py:74、107、122 | `auth:user_sessions:{uid}` 集合会积累已过期的摘要（只在吊销时清理） | 在 create 时用 SSCAN 清理不存在的摘要，或改用 ZSET 存过期时间 |
| S6 | 次要 | app/config.py:350 | `SESSION_COOKIE_SECURE=false` 在生产环境也能启动 | `app_env` 不是 local/test 时设为 false → 启动失败（plan 6.1 auth.yaml 固定规则） |
| S7 | 次要 | app/api/v1/auth.py:43；contract §7.1 | 用户名 4–32 与契约的 3–32 不一致 | T-A05 采纳后端的 4–32，契约已改，后端无需改动；测试按 4–32 写 |
| A1 | 建议 | app/auth/passwords.py:35 | 弱密码表只有 18 条 | 内置常见密码前 1 万条（离线文件），或接 k-匿名 HIBP（需联网，暂不做） |
| A2 | 建议 | app/auth/risk_assessment.py | `ACTIVE_QUESTIONNAIRE=None`，风险测评恒为 400，所有 ⚖ 接口会一直返回 CONSENT_REQUIRED | 由 T-B15 提供问卷；在此之前前端需要给出明确提示（见待决问题） |
| A3 | 建议 | app/auth/consents.py | `REGISTER_DOC_VERSION="unversioned"` 是常量 | 改为读 `auth.yaml`，规则同 M2 |
| A4 | 建议 | app/auth/service.py | `username_taken` 把已删除用户也算作占用（这是正确的，防冒名） | 在注释里写明这是有意为之 |

## 4. 合入条件
1. M1 的 nginx 一行修改（运维）在对外暴露前上线，后端的可信代理列表与 T-B03a 一起做。
2. M2–M4 与 S3、S6 由后端在下一个提交（建议编号 T-B03d，或并入 T-B03a 第一个提交）中完成。
3. 测试 T-T01x 按契约 v0.2.3 #24–#27 增加用例。
