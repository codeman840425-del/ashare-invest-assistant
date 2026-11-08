# T-O33 架构评审隔离环境（运维，2026-11-08 03:39 MST）：已恢复并保留，7 个用例还没跑
候选源码：review/T-O33-candidate afccd5e3cbad48affbce9b95fcda5c32a388cbb5（worktree /workspace/wt-review-T-O33），conditional=true，T-B92 待 ACL 复验，不是正式收口。代码没改，没提交。
接管前确认没人在用（四种方式）：
- fuser：两个 socket 文件都没有进程；
- docker：所有容器（含已退出的）都没有挂载这两个目录；
- 正在运行的 tb58-isolated-pg3 的 mountinfo 里没有这两个路径；
- 直接连接：两个 socket 都返回 ConnectionRefused；作为对照，tb58 的 socket 能连上。
- 限制：box 上没有 lsof；ss 和 /proc/net/unix 看不到其他网络命名空间里的 socket，所以没用它们下结论。
旧目录：改名为 /tmp/tb70-tb91-owned-socket.bak-20261108T103802Z 和 /tmp/tb91-owned-redis.bak-20261108T103802Z，内容原样（含 uid 70 留下的 socket 和锁），没删除。tb92 的两个路径原本就不存在，这次没建。
新资源（都只属于本任务，带标签 aia.task=T-O33-review，--network none，没有 TCP，没改 daemon，没碰其他容器）：
- <host>：timescale/timescaledb:2.31.0-pg16，PostgreSQL 16.15，listen_addresses 为空。socket 在 /tmp/tb70-tb91-owned-socket/.s.PGSQL.5432。本地 trust，postgres 和用例里的角色都免密，只用于合成库。数据放在容器的匿名卷里。
- <host>：redis:7.4.12-alpine，--port 0，socket 在 /tmp/tb91-owned-redis/redis.sock，不落盘，PING 返回 PONG。
- 都和 test_tb91_fixes.py 里写死的 SOCKET 和 REDIS 路径一致。
数据库：t_o33_review，用候选源码执行 alembic upgrade head：rc 0，版本 0027，没有数据。7 个节点的 fixture 会自己建临时库 tb70_p2n02_<uuid>、迁到 head、执行 deploy_grants，用完自己 DROP，不依赖 t_o33_review。
运行方式（给后续用）：在 /workspace/wt-review-T-O33 下 cd src/backend，再 PYTHONPATH=. uv run pytest -q selfchecks/test_tb91_closing.py 加上 T-A42 指定的 7 个节点。用例自带 no_network，只允许 unix socket。
状态：这次没跑任何用例（等 cloud 的 ACL 补丁），也没调麦蕊或外部 HTTP。两个容器保持运行，供架构评审用，不清理；备份目录不动。
