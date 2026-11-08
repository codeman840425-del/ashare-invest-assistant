# T-O24 推送与用户本地升级流程（准备，全部未执行；等 T-B88/T-T22 放行和用户本人批准）
框架来自 DeepSeek 草稿（reports/deepseek/T-O24/draft.md，未核实），已对照 T-O22-upgrade.md 和仓库脚本逐项修正：A2 改成把 origin/main 合入本地 main；B 的启动改用 deploy/scripts/up.sh，不直接 docker compose up。
## A. 推送（快照 2026-11-07 20:35 MST）
- origin/main 是 bd28652（已用 ls-remote 核对）。本地 main 是 55f6433，比 origin/main 多 113 个提交、少 3 个（ops/seg1-merge 那 3 个 merge），不能快进。
- A1 推送前要重新 ls-remote 拿远端 hash；推送点按评审放行的那个提交，不要默认推最新 HEAD。
- A2 `git merge origin/main`（不 rebase、不 force、不改写历史），本地 main 仍是它的后代；有冲突就停手报编排者，不自己解冲突。
- A3 测试补丁：按测试最新报告（T-T22）指定的净补丁和提交来放；只记录流程，不替测试判断。
- A4 对 origin/main..<推送点> 跑扫描，必须 0 命中：gitleaks_run.sh range（隔离 bare 克隆）、secret_scan range、check_real_secrets range。
- A5 `git push origin <推送点>:main`，只允许快进，不加 --force；推送后看 CI 结果。
## B. 用户本地升级（详细步骤见 T-O22-upgrade.md，这里只列差异）
- 迁移链以推送点的 versions/ 为准。当前已提交的 HEAD 是 0019→0020→0022，0021 在 paused/。工作区里有别人未提交的 0023，如果之后入链，要重新核对。
- 用户的 934648b 推断在 0019（未实测）。升级前必须先实测当前版本，不能跳过 0020。
- 升级前用 compose.sh --resolve 记下卷前缀和 AIA_SECRETS_DIR，升级后必须一致；备份 db-backup.sh 和主密钥（含 sha256 台账），备份放在仓库外。
- 用 up.sh 升级（会 build、跑 migrate、timescale-apply、db-roles，再启动服务），之后查 alembic_version 和健康状态。
- 失败就停手保留日志；禁止 down -v、删卷、降级；回退只能用 dump 恢复到新库名验证。
