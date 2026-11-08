# T-O27 preflight：alembic_version 只读授权，集成与隔离验证（运维，2026-11-07 21:25 MST）
结果：通过。本地提交 d313d64f200f6e1467086613740a35f24e8a5bad，父提交 23186d458e655d5536b7c629efb129224b92494d。未 push，未访问用户机。
补丁：sha256 59d5aea0…ce83 校验一致；apply --check 通过，无漂移；只改 grants.sql（+30）和 verify-roles.sh（+20）。在 /workspace/wt-ops-T-O25 应用，共享工作树未动。
静态：git diff --check 通过，bash -n 通过。授权只有 GRANT SELECT ON public.alembic_version TO aia_api, aia_ingest，没有放宽其他权限。没发现代码问题。
隔离：新建容器 o27-pg-iso（timescaledb 2.31.0-pg16，复用镜像，数据是新的），--network none，专属 unix socket，local scram（错误口令被拒），随机凭据存在 /workspace/tmp/o27/pw（700/600）。没用 aia-t01、rv2 或生产库，没调麦蕊。
步骤（退出码）：用已提交源码执行 alembic upgrade head，共 22 步到 0023：0；timescale：0；apply-roles：0；verify-roles：0（122 OK / 0 FAIL）；apply-roles 重跑：0；verify-roles 重跑：0（122/0）。
T-O27 用例：aia_api 和 aia_ingest 各 9 项全过。SELECT 成功；INSERT/UPDATE/DELETE/TRUNCATE 和 ALTER/DROP/CREATE INDEX 都被拒。
矩阵：public.alembic_version 上 aia_api、aia_ingest 只有 SELECT，aia_maint 没有任何权限。验证后版本行仍是 0023。aia_api 读 ciphertext 仍是 f。两个角色在 public 上都没有 CREATE。
扫描：secret_scan staged、tree、range 阻断 0；check_real_secrets not-found；gitleaks 用 bare clone 跑 history 和 range，退出码都是 0；暂存区 gitleaks no leaks。日志里不含口令。
清理：o27 容器、src 副本、socket 已删；保留 log 和 pw；共享资源未动。
DeepSeek：未重调；引用 reports/deepseek/T-O27/ 的已有草稿作为报告框架，内容已自审。
下一步：父任务推送后，在用户机只做重跑 db-roles、重启、自检（verify-roles、8080 / 和 /login、启动版本检查）。
