# 裁定：上游删除后网关返回 502 还是 504（2026-11-07，架构师）
依据：plan.md 第 249 行“网关上游连接超时”写明返回 502/504，走统一错误页，不进契约错误码表；nginx.conf 第 74、238 行的注释也是这样写的。
现象：push-61b0edf 的 CI 冒烟里，删除桩上游后返回 504；nginx_limits_smoke.sh 第 156 行只接受 502。
原因：resolver valid=10s 的缓存窗口内，nginx 仍连旧 IP。旧 IP 不回应时，3 秒的 proxy_connect_timeout 到期返回 504；旧 IP 直接拒绝连接时返回 502。两种结果取决于 CI 宿主的网络栈，网关没有错。
裁定：以 plan 为准，502 和 504 都算通过。改冒烟脚本，不改网关。
运维改 scripts/ci/nginx_limits_smoke.sh 第 156–164 行：
1. 接受 502 或 504，并且仍要求没有 X-Stub 头、挂起不超过 5 秒。
2. 错误码要和状态码对应：502 对应 GATEWAY_UPSTREAM_UNAVAILABLE，504 对应 GATEWAY_UPSTREAM_TIMEOUT。都要带 X-Request-Id 和 private, no-store。
3. POST 那一条同样按实际返回的状态码检查，状态码要原样保留。
4. 第 181–196 行的 SYN 不应答用例仍只接受 504，不改。
5. 换 IP 后在 10 秒内恢复 200 的断言不变。
测试：不涉及 tests/，不用改。
