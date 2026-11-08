# 评审 2a9d141（T-O13：nginx 动态解析上游）

- **结论：通过**。可以推送。
- resolver <host> + 变量 proxy_pass；健康检查探上游。
- 冒烟 `nginx_limits_smoke.sh`：全部通过
  - URI 原样转发，X-Request-Id 透传或重新生成
  - TRACE 走 <at>nginx_405
  - 上游删除后返回 500，不再连旧 IP
  - 上游换 IP 后约 10 秒内恢复，网关全程没重启
- CI：ruff、mypy、静态检查通过；scripts/ci 的测试 230 passed / 55 skipped；meta-json 枚举失败是继承来的。
- 问题：无。
