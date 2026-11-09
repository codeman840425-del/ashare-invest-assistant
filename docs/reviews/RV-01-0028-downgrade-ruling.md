# RV-01 剩余裁定：0028 降级路径（架构师，北京 2026-11-10）

> 范围：仅 RV-01 两处阻断的**剩余项**——0028 降级裸删列风险；creation.py 过滤项已由 T-B98 修复并验收（c869dcf），不在本裁定范围。基线 team-b=98d36ec（含 T-B95 716cda3、T-B98 c869dcf、T-B98b f20fd83）。
> DeepSeek：未用，原因：裁定不外包。

## 1. 风险回顾

0028 的 downgrade 直接 `DROP COLUMN app.risk_control_settings.override_active`。若库中已有 `override_active=false` 的行（用户已清除覆盖），降级会**裸删列**：清除事实丢失，降回 0027 后所有 user 行重新视为有效覆盖——继承语义静默反转，且 `risk_control_settings_history` 的「清除」行（enabled=null, params=null）失去对应状态，审计链与实际状态不一致。RV-01 将其列为上线阻断。

## 2. 现状核查（只读）

T-B98（c869dcf）+ T-B98b（f20fd83）已在 `app/db/migration_check.py::require_safe_downgrade` 与 `migrations/env.py::configure_guarded` 落地守卫：

1. Alembic 用原命令 planner 先解析出**完整降级步骤**，任何 DDL 执行前判断是否含「移除 0028」的步骤（含从后继版本跨至 0027）。
2. 有该步骤时：离线模式直接拒绝（不生成跨界 SQL）；在线模式对 `app.risk_control_settings` 加 `SHARE MODE` 表锁后检查 `EXISTS(override_active=false)`——**有已清除行 → 拒绝降级**（`UNSAFE_DOWNGRADE_0028`），版本保持 0028，无任何 DDL 执行。
3. 无已清除行（false 行为 0）→ 允许降级，列删除无损（没有事实依赖它）。
4. 后继版本先降到 0028（列保留）不受影响；`current`/`check`/`upgrade` 无降级步骤时不查风控行、不取锁。

定点证据（test_tb95_reset.py）：0028→0027/-1/base 拒绝且版本保持 0028、离线跨界不输出 DROP、合成后继跨降拒绝且后继 DDL 未执行、无 false 行往返允许、历史 FK/append-only 完整——T-B98 18 passed、T-B98b 22 passed。

## 3. 裁定

**风险已由既有守卫收口，不追加新守卫、不改 0028 迁移文件。** 理由：

1. 「裸删列」的实际危害前提是「存在已清除行」；守卫恰好在该前提成立时 fail closed（拒绝降级、保持 0028），危害路径被切断。
2. 无已清除行时降级语义无损（列上没有任何需要保留的事实），允许降级是正确的，不必一刀切禁止——与 T-A35 B1（0025 固定抛错冒充可回滚）区分：这里是**有条件守卫**，不是禁用 downgrade。
3. 守卫覆盖含后继版本的一切跨 0028 降级计划，且在任何 DDL 前判定；离线 SQL 同样拒绝生成。已由定点负例证明。

**补充执行口径**（不新增代码，写给运维/后端执行清单）：

- 需要从 0028 降级的场景（仅回滚发版）：先确认 `SELECT count(*) FROM app.risk_control_settings WHERE NOT override_active` = 0；非 0 时**不降级**，按「保持 0028 + 代码回滚到仍含 0028 的版本」处理——0028 是加列迁移，旧代码对该列无感知，保持列不阻塞旧代码运行。
- 该检查属部署前置核验项，与 master_bootstrap 首导核验同列（记入运维部署清单，不占任务号）。
- 真发生「必须降级且有已清除行」的场景：另行申报，走状态保留型专用降级脚本评审（把 false 行翻译成可重建形式再删列），不得现场即兴。

## 4. 收口结论

- RV-01 剩余项（0028 降级裸删列）：**关闭**——守卫已落地（c869dcf+f20fd83）、负例已验证（18+22 passed）、部署口径如上。progress-board 第 6 条的「待架构师裁定」可清除，本项完全收口。
- 上线策略不变：0028 已在用户库（T-T31 真库复验过），无需额外动作。
