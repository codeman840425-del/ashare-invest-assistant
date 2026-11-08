# 评审 f6c36ec（证券搜索专用限流 aia_search；/securities/* 统一 private, no-store）：可推（但不在本段连续推送链内）
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- /securities 的 location 先 proxy_hide_header，再加 add_header always，网关自产的 502/504 也会带头。server 级没有 add_header，所以没有继承丢失的问题。
- 搜索的限流 key 只匹配 /securities/search? 和 /securities?…q=；Retry-After 为 1，等于 ceil(1/5)。
- 实测：check_gateway_limits 0 个问题；对应测试通过。nginx 冒烟测试需要 T-O14，本次未跑。
- m（运维）：efb53b8 引入网关统一错误页后，要复核 /securities 上 502/504 的错误页是否仍然带 private, no-store。
- B/M：无。
