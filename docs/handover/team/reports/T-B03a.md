# T-B03a 报告：防滥用（无验证码）

提交：**57b1c3b**（2026-11-02 05:56，北京时间），仅本地提交，未推送。共改 4 个文件：`app/auth/abuse.py`（新增）、`api/v1/auth.py`、`auth/deps.py`、`config.py`。

## 实现（plan §3.6）
- **限速**：Redis 有序集合滑动窗口。
  - 用 Lua 原子执行，时间取 Redis 的 `TIME`。
  - 超限的请求不计入窗口，返回 `429 RATE_LIMITED`，带 `Retry-After` 头和 `details.retry_after_s`。
  - 限速键使用 IP 的 HMAC，不存明文 IP。
  - 注册：同一 IP 每小时最多 5 次、每天最多 20 次，每次尝试都计数（含参数校验失败）。
  - 登录：同一 IP 每分钟最多 10 次。被限速的请求不写 `login_attempts`，防止刷表。
  - 改密（契约 §7.1「旧密码错误计入 T-B03a 限速」）：按用户计数，只计旧密码错误；每 `lock_base_s`（900 秒）内最多 `lock_after_failures`（5）次，超出返回 429。改密失败不影响登录锁定计数。
- **渐进锁定**
  - 同一用户名连续失败 5 次，锁定 15 分钟；之后每多失败一次时长翻倍（30 分钟、60 分钟……），上限 24 小时。
  - 锁定期间即使密码正确也返回 `403 ACCOUNT_LOCKED`，带 `retry_after_s`。
  - 密码正确即清零失败计数，未批准的账号也一样。
  - 不存在的用户名在 Redis 里按同样规则计数和锁定，避免通过锁定行为泄露用户名是否存在。
- **pending 上限**：全站 pending 账户达到 200 个时，注册返回 `503 REGISTRATION_CLOSED`。
- **login_attempts**：所有进入凭据判断的登录都记一条，`failure_reason` 取值为 invalid_credentials / locked / not_approved。
  - 另提供 `purge_login_attempts()`，删除 180 天前的记录；由谁定时调用归 beat 任务。
- **阈值**：放在 `Settings.auth_abuse`（AuthAbusePolicy），默认值逐条取自 plan §3.6。plan §6.1 还没有对应的 YAML 段，没有新增环境变量。
- **来源 IP**：直接复用 a250379（T-B03b 跟进）的 `TRUSTED_PROXIES` 和「XFF 只取最右一跳」实现。停放的 WIP 里有一份重复的可信代理实现，已删除。

## 验证（隔离容器；没有调用麦蕊，没有碰共享库）
- 代码检查：ruff check 与 ruff format 通过；mypy --strict 检查 49 个文件，无问题。
- 自检脚本
  - `selftest_tb03a.py`：38/38，覆盖注册 429 与 Retry-After、伪造 X-Real-IP 无法绕过、登录 429 不落表、5→15min→30min 递增、锁定期 403、成功后清零、不存在用户名同规则、改密限速、180 天清理、OpenAPI 未新增字段。
  - `selftest_tb16.py`：125/125（已放宽限速阈值，避免批量注册被限）。
  - `selftest_api.py`：205/205。
  - `selftest_xff.py`：21/21。
- 测试方工作树（b0a44e6，设置 AIA_BACKEND_DIR 指向本仓库）：507 passed / 215 skipped / 1 xpassed / 0 failed。
- STOP 文件 sha256 不变；diff 中证书相关命中 0。

## 未做 / 需要他人
- **蜜罐隐藏字段、最短填写时间（<3 秒）**：需要在注册请求里加字段，契约 §7.1 目前没有。需要架构在契约中加字段（例如 `website` 蜜罐、`form_started_at`），之后我再实现。
- **Nginx `limit_req`**：在 deploy/，不属于我的范围，由运维负责。
- **测试方**：可以给限速、锁定、改密限速补用例。注意：批量注册的测试需要调大 `auth_abuse` 阈值。
- **前端**：处理 429（读 `Retry-After`）和 403 ACCOUNT_LOCKED（读 `retry_after_s`）。
