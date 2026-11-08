# 评审 efb53b8（网关 T-A04 ⑥⑦：server 级 proxy_connect_timeout 3s；网关自产的 502/504 走统一错误页）：可推，需与 aa858a8 同批
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在干净导出或临时克隆 /tmp/rv3 里跑，只读，没有推送，没有调用麦蕊。
- error_page 502/504 定义在 server 级，跳到 internal 的 /__aia_errors/50x，两个错误页都 add_header Cache-Control "private, no-store" always，并带 X-Request-Id。
- /securities 的 location 没有自己的 error_page，会继承 server 级设置，所以那里的 502/504 也带 no-store。f6c36ec 上记的那条 m 关闭。
- 实测：check_gateway_limits 0 个问题；scripts/ci/tests 648 通过（在 aa858a8 上）。
- 冒烟测试本提交里只接受 502，而 CI 实测删桩后可能得到 504（见 ruling-gateway-502-504.md），gateway-limits 作业会偶发变红。所以必须和 aa858a8 一起推。
- B/M：无（问题由 aa858a8 修复）。
