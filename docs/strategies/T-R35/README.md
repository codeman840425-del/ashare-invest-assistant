# T-R35｜H-01 / S-01 模拟复盘方案（只读核对；T-A74 定稿修订）

> 事实陈述（编排者提供，本文照录）：H-01 与 S-01 于 2026-11-09 过了 G7 审批。**编排者称用户本人已在私聊授权代办，记录见 `/workspace/team/rules/g7-delegation-2026-11-09.md`；编排者称实际经管理员密码会话操作；条款由架构师另行修订。** 生命周期仍为 `draft`。
> **本文未独立核验用户本人授权**（只读打开了该记录文件并核对文字内容，不把它写成由研究员独立核实的用户确认）。**未关闭项**：条款修订前 `plan.md:996`（及 plan.md:3628、契约 T-A18/T-A20）仍写不允许代批。
> 本文用语一律「候选信号 / 计划条件」，不承诺收益。不写库、不启服务、不调麦蕊、不读凭证、不触发 lifecycle。

## 0. 审批记录核对（代码 / docs，只读）

| 核对项 | 结果 | 出处 |
|---|---|---|
| G7 代码/plan 现行规则 | 仍要求管理员本人浏览器会话 + `password_login` + 密码复核；Bearer/脚本 → `403 HUMAN_SESSION_REQUIRED` | plan.md:996；api-contract.md:953；`promotions.py:55-71` |
| 代办授权记录文件 | 存在；写明用户私聊原话授权编排者代办、H-01/S-01 已批、`ack_warn_gates=["G6"]` | `/workspace/team/rules/g7-delegation-2026-11-09.md`（编排者维护） |
| 研究员独立核实 | **未做**；不把该文件当作已核验的用户确认 | 本任务边界 |
| 生命周期仍 `draft` | 与「审批/晋级两步分离」相容；未调 lifecycle | api-contract.md:960；`reviews.py:401+` |
| 条款修订状态 | T-A74 ① 待用户确认，plan/契约**未改** | docs/reviews/T-A74-rulings.md 文首；team/reports/T-A74.md |

## 1. draft → simulating：前提与操作路径

### 1.1 前提条件

1. `strategy_versions.lifecycle == draft`。
2. 绑定本版本的 promotion review 为 `approved`、非 stale。
3. G1–G6 无 `fail`；每个 `warn` 已在 `ack_warn_gates`（背景为 `[G6]`）。
4. G7 `pass` 且 `compliance_lint.human_review.origin == password_login`（代码路径）。
5. 调用方满足 `human_admin`（现行代码）。

### 1.2 已实现路径

| 步骤 | 接口 | 出处 |
|---|---|---|
| 申请 | `POST /strategy-cards/{card_id}/promotion-requests` | `promotions.py:90+` |
| G7 决定 | `POST /admin/promotions/{review_id}/decision` | `promotions.py` → `reviews.decide` |
| 生命周期 | `POST /admin/strategies/{id}/versions/{vid}/lifecycle` `{to:simulating, review_id, password}` | `promotions.py:211+` → `reviews.change_lifecycle` |
| 字段 | `lifecycle` / `strategy_lifecycle_events` / 审计 | `reviews.py:488-518` |

### 1.3 未实现 / 待定

| 项 | 说明 |
|---|---|
| `simulating→published` 证据链 | 代码硬拒（`reviews.py:476-484`）；**T-A74 B5：本期不做** |
| CLI 绕过人机会话 | 未实现且规则禁止 |
| 普通用户实例化 simulating | MVP 仅管理员；T-B79 待定 |
| 库内 review 行 | 本任务未查库 |

### 1.4 当前是否已满足「可模拟」

按编排者陈述仍 `draft` → lifecycle 未完成。plan 条款修订前，代办与 plan.md:996 文字冲突列为**未关闭项**（见文首）。本文不触发任何 lifecycle 操作。

## 2. 「20 个交易日模拟复盘」指标与阈值

### 2.1 正式口径（plan / 已裁定）

| 指标 / 门槛 | 定义 | 出处 |
|---|---|---|
| 发布样本门槛 | n ≥ 20 **或** 模拟满 20 个交易日；必需字段 `verified_live`；管理员批准 | plan §2.5.13 |
| 跟踪窗 | T+1 / T+5 / T+20 | plan §2.8 |
| 入场价 / 方向正确 / 不可成交 | 见 plan §2.8 / §2.8.1 | 同上 |
| 降权权重 | α=10, β=0.6, γ=0.4, s=5；n<20 → weight=1 | plan §2.5.7 |
| 展示样本 | n<5 不显示；5≤n<30 样本少；n≥30 正常 | plan §2.5.14 H⑧ |

### 2.2 T-A74 定稿（B1–B4；标「待异源复核前的默认裁定」）

> 下列 B1–B4 为架构师 T-A74 默认裁定，**需另一个模型复核**前作为研究员执行默认值；B5 本期不做。

| # | 裁定摘要 | 验收要点 |
|---|---|---|
| **B1** | 「统一 20 日」**只指发布资格窗**；报表仍出 T+1/5/20 三列。发布资格的 n = 该版本在**映射跟踪期**（intraday_t→T+1、short→T+5、swing/long→T+20）上 `state=complete` 且可成交的观测数；「满 20 交易日」按交易日历计 simulating 天数，缺日不推进 | 三列并存；资格：n_映射≥20 或 模拟交易日≥20 |
| **B2** | H-01 **不拆版本**；缺 horizon 的观测**不进 n、不进胜率**，只计 gap（与 `sim_fail_horizon_unknown` 对齐） | 见 §4.2 / T-A74 ②a |
| **B3** | G6 warn+ack 只审计：不挡 simulating 内候选信号、不降权、不把 G6 改写成 pass、不等同 verified_live | weight 仅按 §2.5.7 |
| **B4** | S-01（`horizons:[short]`）报表三列照出，**以 T+5 为主口径**高亮；发布资格按 B1（n 取 T+5 complete，或满 20 交易日） | 不用 20 日替代 RC5 的 5 日预警窗 |
| **B5** | `simulating→published` 证据链**本期不做**；代码继续硬拒 | 保持 `PROMOTION_GATES_NOT_MET` |

## 3. 健康度口径（健康 / 观察 / 退役）

| 跃迁 | 条件 | 出处 |
|---|---|---|
| → `published`（健康） | simulating 满足 B1 资格 + verified_live + 管理员批准（MVP 代码路径未接通，B5） | plan §2.5.13 / §2.8.2 |
| `published` → `observing` | n≥20 且（weight<0.8 连续 5 日 **或** 内部复验<基线 70%） | plan §2.8.2 |
| `observing` → `published` | **weight ≥ 0.9 连续 10 个交易日**，且内部复验恢复（迟滞） | plan.md:1295 |
| `observing` → 提示复审 | weight<0.6 持续 20 日（或内部稳健度<50%×20 日）→ 通知管理员 | plan §2.8.2 |
| → `retired` | 仅管理员确认 | plan §2.5.13 / §2.8.2 |

`observing` 不能从 draft/simulating 手动设置（T-A14）。

## 4. 失败退回与 RC5（口径 B）

- 本人 × 策略版本；失败 ⇔ complete 且 direction_correct=false。
- 映射：intraday_t→1，short→5，swing/long→20（T-A36/T-A37）。
- 缺 horizon → 跳过 + `sim_fail_horizon_unknown`，不默认 5（TB-A48）。
- RC5 只是预警；终评归 §2.5.7 / §2.8.2。

### 4.1 统一 20 日复盘 vs RC5（已定关系）

| 维度 | 复盘 / 发布资格窗（B1） | RC5 预警窗 |
|---|---|---|
| S-01 | 资格可用满 20 日或 T+5 完成数 n；报表以 **T+5 主口径** | short → **5** 日 |
| H-01 v2 | 资格按版本一份 n；报表三列 | 四周期；缺 horizon **只计 gap**，不进 n/胜率；RC5 不回填 swing（**已裁定不拆版本**，T-A74 ②a） |

### 4.2 `ack_warn_gates=[G6]`

仅确认 G6 warn 以便 decision/lifecycle；不改 G6 统计、不升 published（B3）。

## 5. 待办 / 未关闭项

1. **G7 条款修订**：plan.md:996 等仍写不允许代批；T-A74 ① 待用户确认后由架构师修订（研究员不改 plan.md）。
2. B1–B4 **待异源复核**（另一个模型）。
3. B5 published 证据链立项时机（本期不做）。
4. 后端/测试：H-01 缺 horizon 定点用例（T-A74 ②a 派给后端/测试，非本单实现）。

## 6. 辅助

见 `metrics_slots.json`（B1 相关 pending 已按 T-A74 更新）。DeepSeek 字段槽草稿见 team/reports/deepseek/T-R35/（历史）与 T-R36/。
