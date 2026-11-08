# review-c104c05（T-O19）  结论：通过（m 级），但链上位于 b4539c2 之后，本次推不了
- SPA：location / 用 try_files 回退 index.html；/api/ 前缀反代，后端的 404 原样透传；502/504 走 server 级 error_page 到精确的 /__aia_errors/*，不会被 SPA 吞。✔
- m1：`/api`（不带斜杠）和 `/apifoo` 会落到 SPA 返回 200 HTML，建议加 `location = /api { return 404; }`。
- 缓存：/assets/ 用 `try_files $uri =404` + public, max-age=31536000, immutable；index.html 是 no-store（比 no-cache 更严，可接受）。/securities 仍是 private, no-store。✔
- 安全头：server 级没有任何 add_header，所以不存在被子 location 覆盖的问题。m2：开始出 HTML 后缺 X-Content-Type-Options / X-Frame-Options / Referrer-Policy，建议后续补到每个 location，或用 include 片段统一加。
- 镜像：上下文是 src/frontend，只 COPY 白名单文件，没有 .env 或密钥；frozen lockfile；最终基础镜像与原 digest 相同。✔
- scripts/ci/tests：667 passed / 55 skipped；check_frontend_deploy、check_gateway_limits、secret-boundary、compose-logging 全 OK。镜像构建和冷启动冒烟交给 CI。
