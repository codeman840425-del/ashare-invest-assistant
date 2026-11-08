# T-O25 推送前准备（运维，2026-11-07 20:53 MST；未推送）
待推 hash：bcb61a376ec72aa77c7b887b24d4edb3b8724b3d（merge 提交）。parents：acb6597168bb896e18de28d639fe988af707e8fe、bd28652c06f4ba0ca67778d6a937c5a8864d55ca（=origin/main，已用 ls-remote 核对）。从 bd28652 是快进，共 118 个提交。
位置：独立 worktree /workspace/wt-ops-T-O25，分支 ops/T-O25。共享 main 仍在 a305d14，没动它的工作树和 index，之后要单独同步。
补丁（内容未改，都只改 tests/）：
- T-T21-tests-only.patch（sha256 5c8b95a0af50…，5 个文件）→ eb716d5；T-T22-tests-only.patch（sha256 3626e140f94a…，3 个文件）→ acb6597。
- 合入前 main 里没有等效提交（3b2c8ec 不在 main 上）；两个补丁 apply --check 都通过；每次暂存后 gitleaks 0、secret_scan 0/0。
merge：`git merge --no-ff origin/main`，没有冲突，merge 后的文件树和 acb6597 完全相同。迁移（a305d14 新增 0023）：
- alembic heads 只有一个 0023；history 是 0019→0020→0022→0023，0021 留在 paused/，不在链上；
- 0023 只是把 master_snapshots.source 和 listing_status_history.reason 的 CHECK 约束改宽（新增 mairui_list，原有取值不变），不改写数据，也没有新表。这些只是离线检查和静态阅读，没在真实库上升级过。
扫描：
- gitleaks_run.sh history（隔离 bare 克隆）：0；range bd28652..bcb61a3：0；secret_scan tree：849 个文件 0/0；secret_scan range 646 个 0/0；check_real_secrets range：not-found。
用户升级风险：
- 从 0019 要依次跑 0020→0022→0023，不能跳过；
- 0023 先删再建 CHECK 约束，会短暂加 ACCESS EXCLUSIVE 锁，并全表校验；新约束是旧取值的超集，已有数据应能通过，但没在真实数据上验证；
- 新的 mairui_list 来源可能还需要给 worker 补授权，我没深查，交后端确认；升级前要先备份库和主密钥。
步骤：reports/T-O24-push-upgrade.md 和 T-O22-upgrade.md 照旧，只是目标 head 改为 0023、推送点改为 bcb61a3。
DeepSeek：用于本报告的通用小节框架（产出目录 reports/deepseek/T-O25/，deepseek-flash，20:51 MST；只发了公开的占位文字，草稿已复核）。
待办：
- 用户本人批准后执行 `git push origin bcb61a3:main`（快进，不 force），推后看 CI；
- 推后把共享 main 同步过来：在 /workspace/ashare-invest-assistant 执行 `git merge --ff-only ops/T-O25`，要先确认工作区干净，不能 stash 别人的文件。
