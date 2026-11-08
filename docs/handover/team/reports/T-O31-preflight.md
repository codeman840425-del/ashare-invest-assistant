# T-O31 preflight：缺失 assets 返回干净 404（运维，2026-11-08 16:58 北京时间）：已验证，待裁定，不是完成验收，未提交
补丁：sha256 95c9faba…2b61 校验一致；在独立的 detached worktree /workspace/wt-ops-T-O31（基线 3d3612e）上 apply --check 通过并应用；改动已暂存，没有提交。
范围：5 个文件，+69/-25：nginx.conf（在 /assets/ 加 error_page 404 <at>assets_missing，返回纯文本 "not found\n"）、check_frontend_deploy.py、frontend_gateway_smoke.sh、frontend_root_smoke.sh、test_frontend_deploy.py。没动业务 src、tests 或 docs。
静态：diff --check、bash -n、sh -n 通过；check_frontend_deploy 0 个问题；test_frontend_deploy 14 passed；check_gateway_limits 0 个问题（需要 pyyaml，和 CI 一样用 uv）；test_gateway_limits 130 passed。
smoke 静态核对：新版 root smoke 改成把 root 指到临时 dist，不再写 /usr/share/nginx/html，并且会前后核对仓库 conf 和共享目录有没有被改。即便如此，仍在 bwrap 里隔离跑：/usr/share、/etc、/tmp、/var 都用 tmpfs，--unshare-net、--unshare-pid。nginx 二进制取自 nginx<at>sha256:54f2a904…（1.31.2，和镜像同一个 digest）。
smoke 结果：rc 0，10/10 OK。宿主上没有 /usr/share/nginx 和 /etc/nginx；worktree 未被改写。
自测探针（同样在 bwrap 里，假上游）：
- /、/login、/research/notes 返回 200 SPA；/assets/a.js 返回 200，Cache-Control 是 immutable；
- /assets/missing.js、/assets/sub/missing.css、/assets/ 返回 404，正文是 "not found"；
- /assetsx 走 SPA 回退 200（不属于 /assets/ 前缀）；
- /api/v1/assets/x 由 API 处理，没被 assets 拦截；/health/live 和 /api/v1/health/live 转发到假上游；/healthz 返回 ok；
- 证券搜索连发 30 次：21 次 200，9 次 429，限流正常。
缺失 asset 的 404 响应头原样记录：Server: nginx（无版本）、Content-Type: text/plain、Content-Length: 10、Cache-Control: public, max-age=31536000, immutable。
待裁定和观察（交编排者/cloud，我没下结论）：
1. Server: nginx 头仍在，“无服务器标识”是否只限正文，等编排者裁定；
2. 缺失资源的 404 也带了一年 immutable 缓存，是否合适请 cloud 确认；
3. 这条和本补丁无关：用 --path-as-is 请求 /assets/../api/v1/health/live 时，会进 /api/ location，但上游收到的是没规范化的原始路径，这是 /api/ 的 proxy_pass 不带 URI 的既有行为。
扫描：secret_scan staged、tree（904 个文件）、files 阻断 0；gitleaks staged no leaks；history 退出码 0；check_real_secrets not-found。还没有提交，所以没跑 range。
DeepSeek：未新调；引用 reports/deepseek/T-O31/ 的 404 清单框架。
清理：bwrap 用的临时 rootfs 已删；保留 /workspace/tmp/o31 的日志和探针脚本。没跑全量回归，没 push，没部署，没访问用户机。
