# T-O26 推送前准备：合入 T-B89 修复（运维，2026-11-07 21:12 MST；未推送，没访问用户电脑）
待推 hash：23186d458e655d5536b7c629efb129224b92494d（merge 提交）。parents：bcb61a376ec72aa77c7b887b24d4edb3b8724b3d（原 tip，即 origin/main）和 750e2ed6536da94389bc44cdc7471b4d9a9d60bd（T-B89）。
基线：worktree /workspace/wt-ops-T-O25 的 ops/T-O25 合并前 tip 是 bcb61a3；ls-remote 显示 origin/main 也是 bcb61a3，没有变化。从 origin/main 推到 23186d4 是快进。共享 main 的工作区和 index 都没动。
祖先核对：750e2ed 只比 bcb61a3 多它自己 1 个提交（父 a305d14，a305d14 已在 bcb61a3 里），没有夹带别的提交。
范围：bcb61a3..23186d4 的改动只有 2 个文件：
- 0023_t_b85b_mairui_source.py（+7/−2，DROP 和 CREATE 两处约束名改用 op.f(name)）；
- 新增 selfchecks/test_tb89_full_migrations.py（+402）。
- merge 用 --no-ff，没有冲突，没有 force/rebase/reset。
迁移证据（只核对后端已有日志，我没重跑）：
- T-B89-before-fix.log：2 failed，就是同一个约束不存在的错误；
- T-B89-after-fix.log：3 passed。三个用例：空库全链到 0023；0019 带数据升到 0023，原数据保持；模拟旧故障时整体回滚到 0019，修复后重跑成功。
- 合并后 alembic heads（离线）只有一个 0023，0021 仍在 paused 里。
扫描（按 T-O24 口径，私有日志 /workspace/tmp/o26/）：
- gitleaks_run.sh history 0；range bcb61a3..23186d4 0；
- secret_scan tree 850 个文件 0/0；range 9 个文件 0/0；
- check_real_secrets range：两项都 not-found。没有新增命中。
DeepSeek：用于本报告的通用小节框架（产出目录 reports/deepseek/T-O26/，deepseek-flash，21:11 MST；只发了通用占位文字）。草稿已复核。
推送后续（这一阶段不执行）：用户批准后 `git push origin 23186d4:main`（快进）。用户机 <path> 用 Windows git fetch，再 `merge --ff-only 23186d4`，然后在 WSL 重跑 up.sh，目标版本 0023。
- 原备份 /root/aia-backups/T-O25-20261108T035513Z、密钥、卷和项目名都不动；升级前先实测库版本（应仍是 0019）。
- 升级后检查 db-roles 和 8080 与 /login；用户的服务目前仍然停着。
