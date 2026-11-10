# 接手从这里开始

更新约定：每次收口更新本文件，注明更新日期（America/Denver）与基线哈希。
本次更新：2026-11-10（America/Denver）；基线 `origin/main=e44311a018270d4db2c111ca04015ff3b86c10a8`。

本文是用户 Windows 电脑上新团队（仓库 `F:\ashare-invest-assistant`，分支前缀 `tb-`）第一份必读。未合入 `origin/main` 的文件用 `git show <分支>:<路径>` 阅读，不要当作已在工作树里。

## 阅读顺序（必读）

1. 本文。建立阅读顺序、用户决定项与当前卡点。状态：本分支 `docs/T-A113` 新增，未入 `origin/main`。
2. [`docs/handover/README.md`](README.md) — 交接手册入口，及其下列出的阅读顺序。状态：已在 `origin/main`；本基 `docs/T-A110=3c0fb54` 在阅读顺序加了数据验证第 5 条；`docs/T-A109=ffddab6` 改了签字栏里的 G7 表述（未合）。
3. [`docs/handover/progress-board.md`](progress-board.md) — 判断哪些已落地、哪些仍待复审。状态：已在 `origin/main`；G7 相关两处更新在 `docs/T-A109=ffddab6`（未合）。
4. [`docs/handover/roles-rules.md`](roles-rules.md) — 角色写入边界与审批权限。状态：已在 `origin/main`；G7 代批表述更新在 `docs/T-A109=ffddab6`（未合）。
5. 仓库内规则（对应仓库外团队规则原档；均已在 `origin/main`）：
   - [`docs/handover/team/token-rules.md`](team/token-rules.md) — 全组额度与避免浪费的规则。
   - [`docs/handover/team/rules/standing-auth-2026-11-08.md`](team/rules/standing-auth-2026-11-08.md) — 2026-11-08 推送 `origin/main` 与本机部署的长期授权边界（不含对外部署、删除用户数据或私样本、对外消息、麦蕊限额等）。
   - [`docs/handover/team/rules/budget-2026-11-07.md`](team/rules/budget-2026-11-07.md) — 省额度、主线范围与并行上限。
   - [`docs/handover/team/rules/deepseek-offload.md`](team/rules/deepseek-offload.md) — 机械整理可外包的范围与复核要求。
   - [`docs/handover/team/rules/no-idle-2026-11-08.md`](team/rules/no-idle-2026-11-08.md) — 交任务须同时申请下一单。
6. [`docs/handover/local-operations.md`](local-operations.md) — 本机隔离回放、版本与迁移门槛、部署方法。状态：已在 `origin/main`；G7 指针更新在 `docs/T-A109=ffddab6`（未合）。
7. [`docs/handover/private-prerequisites.md`](private-prerequisites.md) — 须另行补齐的密钥与私有样本（只列名称与用途，不含值）。状态：已在 `origin/main`；G7 指针更新在 `docs/T-A109=ffddab6`（未合）。
8. [`docs/handover/NEW-ACCOUNT-SETUP.md`](NEW-ACCOUNT-SETUP.md) — 新账号建队步骤。状态：已在 `origin/main`。
9. [`docs/handover/team/README.md`](team/README.md)、[`docs/handover/team/bots/bot-profiles.md`](team/bots/bot-profiles.md) — 脱敏团队资料与角色设定。状态：已在 `origin/main`。历史记录不视为新派单。
10. [`docs/handover/data-validation-handoff.md`](data-validation-handoff.md) — 续做 G2 剩余键（F21/F23/F14/F15）与 T-B86/T-B59 的步骤、计数与掉线幂等。状态：本基已含（`docs/T-A110=3c0fb54`），未入 `origin/main`。附属：[`data-validation/README.md`](data-validation/README.md)、[`t-b86-ledger-summary.json`](data-validation/t-b86-ledger-summary.json)（同基）。
11. `docs/reviews/T-A109-g7-delegation.md` — G7 代批条款与 `draft→simulating` 步骤。状态：未入 `origin/main`，在 `docs/T-A109=ffddab6`（亦含于 `docs/T-A112=ebdab40`）。
12. `docs/reviews/T-A112-h01-v3-rulings.md` — H-01 v3 证伪口径 P-1~P-8 裁定与落卡前提。状态：未入 `origin/main`，在 `docs/T-A112=ebdab40`。
13. [`docs/reviews/cross-review-R1-R19.md`](../reviews/cross-review-R1-R19.md) — 异源复核 R1–R19 / B1–B4 交接包。状态：已在 `origin/main`；T-A112 新增两条非阻塞残留，在 `docs/T-A112=ebdab40`（未合）。
14. 部署 runbook（均已在 `origin/main`；`wrapup-deploy` / `master-data` 在 `deploy/runbooks/`，不在 `docs/`）：
    - [`docs/runbook/windows-local.md`](../runbook/windows-local.md) — Windows + WSL 本地启动。
    - `deploy/runbooks/wrapup-deploy.md` — 收口部署红线与步骤（默认 dry-run）。
    - `deploy/runbooks/master-data.md` — 证券主数据首次导入与词表校验。
    - `deploy/runbooks/ingest-halt.md` — 停机标志；解除须用户本人确认。
    - `deploy/runbooks/networks.md`、`database.md`、`closeout.md` — 网络拆分、数据库运维、收口预演。
15. `docs/strategies/`（只引用，由策略研究员维护；已在 `origin/main`）— 策略库目录，入口见 `catalog.md`，晋级门槛见 `card_promotion_gates.md`。本导航不改该目录。
16. [`docs/plan.md`](../plan.md) 与 [`docs/api-contract.md`](../api-contract.md)（已在 `origin/main`；G7 正文修订在 `docs/T-A109=ffddab6`，未合）。先读 plan §0 结论摘要、§0B 设计原则、§0A MVP 主线、§2.1A 唯一出口、§2.5 策略库（尤其 2.5.0B G1–G7、2.5.13 生命周期）、§7 风险与合规；契约 §1 通用约定、§6 状态机、§7.4–7.6 策略/实例/候选、§7.9 管理端（含 G7 决定）。当前最小切片：[`docs/plan-phase2-next.md`](../plan-phase2-next.md)（已在 `origin/main`；T-A109 有一处同步，未合）。

## 用户本人决定项

新团队不得自行推定。清单位置：
- [`data-validation-handoff.md`](data-validation-handoff.md) 第 4 节「须用户本人决定的事项」（本基已含）；
- `docs/reviews/T-A109-g7-delegation.md` 第 7 节「未决」（`docs/T-A109=ffddab6`，未合）；
- 解 HALT / 恢复出网：同上交接手册第 4 节第 5 条，以及 `deploy/runbooks/ingest-halt.md`「解除停机标志（必须由用户本人确认）」；T-A109 未改这条。

当前已知项（一行一条）：
- 是否重新授权麦蕊调用（交接后须重授权；写明覆盖哪些段）。
- 次数上限（是否沿用本批剩余，或另给新上限）。
- 是否授权 T-B59 的 7 次，以及是否计入或独立于次数上限。
- G7 代批是否扩出 H-01 / S-01（现行书面授权只覆盖这两张卡）。
- S18（E1/X4）产品接受度。
- 是否解除 HALT / 恢复出网。

## 当前卡点

H-01、S-01 仍不能代批（缺证据未清零；不放松「缺证据不得批」）。剩余缺项：
- H4：策略研究员按 T-A112 裁定落 H-01 v3 后，架构师再复核（落卡不自动通过）。
- H12 / S12 / S20：测试（T-T63）补执行链用例。
- S18：由用户本人确认产品接受度。
- 步骤 A：在目标环境只读抄录库内 G1–G6 的 `gate` / `result` / `stale`（不抄 detail）。

S3 已在未合入 main 的研究员提交上确认一致，合入后可从缺证清单去掉。
