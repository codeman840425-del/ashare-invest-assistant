# T-O28 preflight：nginx root 修复，集成与隔离验证（运维，2026-11-07 21:37 MST）
结果：通过。本地提交 34c88c3b1ad9c0d37eeac29418d049c36671c889，父提交 d313d64f200f6e1467086613740a35f24e8a5bad。未 push，未访问用户机。
补丁：sha256 4b42b471…fdc3 校验一致；apply --check 通过，无漂移。在 /workspace/wt-ops-T-O25 应用（应用前干净）。
改动范围：4 个文件，+211 行。nginx.conf 只加了一行 root 加注释；改了 check_frontend_deploy.py；新增 frontend_root_smoke.sh（755）；改了 test_frontend_deploy.py。没动 src、tests、docs。
静态：diff --check、bash -n、sh -n 都通过；check_frontend_deploy 0 个问题；pytest test_frontend_deploy 12 passed。
smoke 复核：脚本会临时写入 /usr/share/nginx/html（index.html、assets/probe.js），最后再恢复。这是共享写风险，所以不在宿主上直接跑。
隔离方式：用 bwrap 隔离。
- /usr/share、/etc、/tmp、/var/log、/var/cache 都是 tmpfs，其余只读；--unshare-net、--unshare-pid。
- nginx 二进制取自本机已有的 nginx<at>sha256:54f2a904…（与 frontend.Dockerfile 固定的 1.31.2 是同一个 digest），通过 docker export 取出，用 musl loader 运行。没装包，没起容器服务。
- 结束后宿主上没有 /usr/share/nginx 和 /etc/nginx。临时 rootfs 已删。
动态结果：rc=0，7/7 OK。
- 缺 root 时 / 返回 500，日志是内部重定向循环；
- / 和 /login 返回 200，是探针页；已有 asset 200 且长期缓存；缺失 asset 404 且不是 HTML；
- /health/live 反代到假上游正常；/healthz 由 nginx 自答。
限制：没跑 Docker bridge 网关 smoke，没用真实前端 dist（用的是探针页）。
扫描：secret_scan staged、tree（851 个文件）、range 阻断 0；check_real_secrets not-found；gitleaks 用 bare clone 跑 history 和 range，退出码都是 0；暂存区 gitleaks no leaks。
DeepSeek：未重调；引用 reports/deepseek/T-O28/ 已有的草稿。
下一步：父任务推送后，在用户机 ff 到 34c88c3，只重启 nginx 并做 HTTP 自检，不迁移。
