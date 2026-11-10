# 接手从这里开始

更新约定：每次收口更新本文件，注明更新日期（America/Denver）与基线哈希。
本次更新：2026-11-10（America/Denver）；基线 `origin/main=00538a1760d704eab6c36789ae36a0784a9566b9`（第 10 批：`docs/T-A117b=34fcd50` 经 `250a3e0`、`12e032a` 链、`be/T-B122=894a882` 经 `bf28d6e`、`ops/T-O73=6e91447`）。此前第 9 批 `3ede1c2c0fbc46da0aca159b337037fd7e32f5e5`、第 8 批 `e44311a018270d4db2c111ca04015ff3b86c10a8` 仅作历史引用。

本文是用户 Windows 电脑上新团队（仓库 `F:\ashare-invest-assistant`，分支前缀 `tb-`）第一份必读。未合入 `origin/main` 的文件用 `git show <分支>:<路径>` 阅读，不要当作已在工作树里。

## 阅读顺序（必读）

1. 本文。建立阅读顺序、用户决定项与当前卡点。状态：已在 `origin/main`（`docs/T-A113=8cfb4bd`，哈希与 G7 状态经 `docs/T-A117` / `T-A117b=34fcd50` 合入）；本提交 `docs/T-A122` 再更新至第 10 批，待合入。
2. [`docs/handover/README.md`](README.md) — 交接手册入口，及其下列出的阅读顺序。状态：已在 `origin/main`；`docs/T-A110=3c0fb54` 所加数据验证第 5 条、`docs/T-A109=ffddab6` 签字栏 G7 表述均已合入。
3. [`docs/handover/progress-board.md`](progress-board.md) — 判断哪些已落地、哪些仍待复审。状态：已在 `origin/main`；T-A109 的 G7 相关两处已合入。
4. [`docs/handover/roles-rules.md`](roles-rules.md) — 角色写入边界与审批权限。状态：已在 `origin/main`；T-A109 的 G7 代批表述已合入。
5. 仓库内规则（对应仓库外团队规则原档；均已在 `origin/main`）：
   - [`docs/handover/team/token-rules.md`](team/token-rules.md) — 全组额度与避免浪费的规则。
   - [`docs/handover/team/rules/standing-auth-2026-11-08.md`](team/rules/standing-auth-2026-11-08.md) — 2026-11-08 推送 `origin/main` 与本机部署的长期授权边界（不含对外部署、删除用户数据或私样本、对外消息、麦蕊限额等）。
   - [`docs/handover/team/rules/budget-2026-11-07.md`](team/rules/budget-2026-11-07.md) — 省额度、主线范围与并行上限。
   - [`docs/handover/team/rules/deepseek-offload.md`](team/rules/deepseek-offload.md) — 机械整理可外包的范围与复核要求。
   - [`docs/handover/team/rules/no-idle-2026-11-08.md`](team/rules/no-idle-2026-11-08.md) — 交任务须同时申请下一单。
6. [`docs/handover/local-operations.md`](local-operations.md) — 本机隔离回放、版本与迁移门槛、部署方法。状态：已在 `origin/main`；T-A109 的 G7 指针已合入。
7. [`docs/handover/private-prerequisites.md`](private-prerequisites.md) — 须另行补齐的密钥与私有样本（只列名称与用途，不含值）。状态：已在 `origin/main`；T-A109 的 G7 指针已合入。
8. [`docs/handover/NEW-ACCOUNT-SETUP.md`](NEW-ACCOUNT-SETUP.md) — 新账号建队步骤。状态：已在 `origin/main`。
9. [`docs/handover/team/README.md`](team/README.md)、[`docs/handover/team/bots/bot-profiles.md`](team/bots/bot-profiles.md) — 脱敏团队资料与角色设定。状态：已在 `origin/main`。历史记录不视为新派单。
10. [`docs/handover/data-validation-handoff.md`](data-validation-handoff.md) — 续做 G2 剩余键（F21/F23/F14/F15）与 T-B86/T-B59 的步骤、计数与掉线幂等。状态：已在 `origin/main`（`docs/T-A110=3c0fb54`）。附属：[`data-validation/README.md`](data-validation/README.md)、[`t-b86-ledger-summary.json`](data-validation/t-b86-ledger-summary.json)（同入）。
11. `docs/reviews/T-A109-g7-delegation.md` — G7 代批条款与 `draft→simulating` 步骤。状态：已在 `origin/main`（`docs/T-A109=ffddab6`）。
12. `docs/reviews/T-A112-h01-v3-rulings.md` — H-01 v3 证伪口径 P-1~P-8 裁定与落卡前提。状态：已在 `origin/main`（`docs/T-A112=70dcd8c`；未推的 `ebdab40` 已被替换，勿再当现行提交）。
13. [`docs/reviews/cross-review-R1-R19.md`](../reviews/cross-review-R1-R19.md) — 异源复核 R1–R19 / B1–B4 交接包。状态：已在 `origin/main`；T-A112 新增两条非阻塞残留已随 `70dcd8c` 合入。
14. 部署 runbook（`wrapup-deploy` / `master-data` 在 `deploy/runbooks/`，不在 `docs/`）：
    - [`docs/runbook/windows-local.md`](../runbook/windows-local.md) — Windows + WSL 本地启动（已在 `origin/main`）。
    - `deploy/runbooks/wrapup-deploy.md` — 收口部署红线与步骤（默认 dry-run）。已在 `origin/main`（第 10 批含 `ops/T-O73=6e91447` 的 seed 节）。
    - `deploy/scripts/wrapup/start-stack.sh` — 启栈脚本。现行 `origin/main` 在 db-roles 之后直接启 worker，**尚未**插入 seed。`ops/T-O73b=695078b`、`ops/T-O73c=7250c2d` 已由架构师 T-A121 判可合、将随第 11 批入 main；顺序见 `7250c2d` 上该脚本 :115–117（db-roles → seed → 启 worker 等）。
    - `deploy/runbooks/master-data.md` — 证券主数据首次导入与词表校验。
    - `deploy/runbooks/ingest-halt.md` — 停机标志；解除须用户本人确认。
    - `deploy/runbooks/networks.md`、`database.md`、`closeout.md` — 网络拆分、数据库运维、收口预演。
15. `docs/strategies/`（只引用，由策略研究员维护；已在 `origin/main`）— 策略库目录，入口见 `catalog.md`，晋级门槛见 `card_promotion_gates.md`。本导航不改该目录。
16. [`docs/plan.md`](../plan.md) 与 [`docs/api-contract.md`](../api-contract.md)（已在 `origin/main`；T-A109 的 G7 正文修订已合入）。先读 plan §0 结论摘要、§0B 设计原则、§0A MVP 主线、§2.1A 唯一出口、§2.5 策略库（尤其 2.5.0B G1–G7、2.5.13 生命周期）、§7 风险与合规；契约 §1 通用约定、§6 状态机、§7.4–7.6 策略/实例/候选、§7.9 管理端（含 G7 决定）。当前最小切片：[`docs/plan-phase2-next.md`](../plan-phase2-next.md)（已在 `origin/main`；T-A109 的同步已合入）。

## 用户本人决定项

新团队不得自行推定。清单位置：仓库外看板 `/workspace/team/board.md`「待用户决定项」专节（只读，不在本仓库）；[`data-validation-handoff.md`](data-validation-handoff.md) 第 4 节；`docs/reviews/T-A109-g7-delegation.md` 第 7 节；解 HALT / 恢复出网另见交接手册第 4 节第 5 条与 `deploy/runbooks/ingest-halt.md`。

当前已知项（一行一条；与看板专节对齐，并纳入 04:34 MST 已裁定要新增的 seed 项）：
- S18（G7 S-01，须用户本人；E1/X4 产品接受度）。
- G7 代批范围：仅 H-01 / S-01 还是全部卡长期；是否覆盖 H-01 v3。
- G1–G6 对 v3 重跑结果确认。
- `DAILY_HTTP_LIMIT`（不放宽，除非用户本人）。
- 空匿名卷处理。
- T-B59 的 7 次补证（是否授权，以及是否计入或独立于次数上限）。
- 主数据导入授权（standing-auth 未覆盖）。
- 新团队麦蕊重授权及次数上限（交接后须重授权；写明覆盖哪些段）。
- 是否解除 HALT / 恢复出网（须用户本人确认）。
- F21 原始响应私下交接方式。
- 部署时 seed 写配置行是否在 `standing-auth-2026-11-08` 内，需用户本人确认（编排者裁定为在内，收口时请用户本人确认；架构师 T-A121 记录该文件与用户原话未明确涵盖此写入）。

## 当前卡点

H-01、S-01 仍不能代批（缺证据未清零；不放松「缺证据不得批」）。

G7 计数暂按编排者口径 **37 一致 / 0 不一致 / 3 缺证据**（待架构师评审 T-R53 后再改）。仍缺 H12、S12（待策略研究员 T-R53b 在 g7_review 落文、架构师评审通过后计一致）、S18（须用户本人答复）。S20 按该口径已一致。本导航不改 `docs/strategies`。

engine_policy 顶层与 `hold_risk_monitor` 组件的 2→3，以及 `src/backend/selfchecks/test_tb71_import.py` 离线 a–d（`test_formal_offline_identities_snapshots_and_policy_digests`），已随第 10 批合入（`bf28d6e` / `894a882`）。在 `00538a1` 上核对：`config/engine_policy.yaml:2` 与 `:18` 均为 3。此项不再列为代批前置。

代批前置（收窄后，见团队报告 T-A120 ③；其中 T-O73b (i)–(iii) 已由 T-A121 判收口，待随第 11 批入 main）：
- 步骤 A（库内 G1–G6 结果只读副本），并对 v3 重跑 G1–G6；
- 用户确认 2026-11-09 授权是否覆盖 v3，以及是否覆盖 H-01 / S-01 以外；
- S18 待用户本人回答；
- 2026-11-09 13:12:55（America/Denver）那次代批须重做（当时缺证据，不得用于晋级）；
- 正式卡 v3 `--apply` 导入步骤待补，且须用户本人授权；
- T-O73b (i)–(iii) 已由 T-A121 判收口，待入 main；
- 部署后在用户 Windows 实例上做只读核验（含「G7 批此行」）。

## engine_policy seed

路径（`git ls-files` 已核）：`deploy/runbooks/wrapup-deploy.md`（第 10 批已含 seed 节）、`deploy/scripts/wrapup/start-stack.sh`。将 seed 插入启栈顺序、只认 `inserted=0/1`、失败不启 worker 且不删行，以及手册授权口径修正，在 `ops/T-O73b=695078b` / `ops/T-O73c=7250c2d`；二者尚未入 main，已由架构师 T-A121 判可合、将随第 11 批入 main。顺序见 `7250c2d` 上 `start-stack.sh` :115–117：db-roles 之后、worker 之前执行 seed。部署后 seed 仅认 `inserted=0` 或 `1`；失败不启 worker、不删行。正式卡 `--apply` 须用户本人授权。

## 合并门禁（o61）

今后凡改 `src/backend/app/signals/service.py` 或 `tests/backend/unit/test_g7_board_in_universe_prod_t_t66.py`，合并门禁须在 o61 重跑该文件两条 DB 用例（行号按 `00538a1` 核对）：`test_write_candidate_persist_excludes_bse_via_service_355`（:372）与 `test_write_candidate_persist_admits_main_board_via_service_355`（:383）。CI 能否跑这两条列为低优先级待办。
