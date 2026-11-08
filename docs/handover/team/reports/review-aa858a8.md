# 评审 aa858a8（运维 T-O14：nginx_limits_smoke 在上游删除后接受 502 或 504）：可推，需与 efb53b8 同批
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在干净导出或临时克隆 /tmp/rv3 里跑，只读，没有推送，没有调用麦蕊。
- 位置：在 main 上，是当前 HEAD（父提交 9059bfb），不在单独的分支上。
- 逐条对照 ruling-gateway-502-504.md：
  - ① 502 和 504 都接受，仍然要求没有 X-Stub 头，挂起不超过 5 秒；
  - ② 502 对应 GATEWAY_UPSTREAM_UNAVAILABLE，504 对应 GATEWAY_UPSTREAM_TIMEOUT，都要带 X-Request-Id 和 private, no-store（cc_only）；
  - ③ POST 按这一次实际返回的状态码核对，状态行原样保留；
  - ④ SYN 不应答的用例和 ⑤ 10 秒内恢复 200 的断言都没改。
- 实测：bash -n 语法通过；scripts/ci/tests 648 通过。本机 dockerd 是 bridge=none，冒烟脚本要建 bridge 网络，本次没跑，留给 CI 的 gateway-limits 作业验证。
- B/M：无。
