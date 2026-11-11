# T-R68：P1–P10 判读字段映射表（出数即判）

> 版本 v1.0｜任务 T-R68｜2026-11-11 北京时间｜维护：策略研究员
> 定位：把 T-R59 判定框架（`docs/strategies/T-R58/judging_framework.md`）的每条判据/红旗，映射到正式跑三件套
> （`summary.json` / `trials.csv` / `legs.csv`）的**确切字段路径**，供出数后 10 分钟内完成红旗预筛。
> 依据：T-R58 方案（`retest_plan.md` @6814edc）§8.3/§9；runner 实现（`ds/T-B136`：`judgement.py`、`runner.py`、`runner_data.py`）；
> 正式跑 schema 以 `T-B136-official` 产物实读为准。**本表只做读数字段定位，不新增阈值、不替代方案 §8 的通过标准。**

## 0. 三件套 schema 速查

| 文件 | 结构 | 关键列/键 |
|---|---|---|
| `summary.json` | 顶层键：`plan`、`data`、`coverage`（T-R65 起）、`segments`、`seed`、`splice`、`exclusions`、`checks`、`criteria`、`delisting`、`multiplicity`、`conclusion`、`holdout_by_source` | `criteria.P1…P10`、`checks.L1…L14 + bar_quality`、`data.{st_coverage,listing_coverage,termination_list_sha256}`、`exclusions.<year>.<reason>` |
| `trials.csv` | 16 列 × 每 phase 每候选一行 | `trial_id`(=phase/candidate)、`group`(=A/B/CA/CB)、`phase`、`segment`、`start`、`end`、`params`(JSON)、`holm_family`、`n`、`mean_bp`、`ci_low_bp`、`ci_high_bp`、`selected`、`status`、`started_at`、`elapsed_seconds` |
| `legs.csv` | 41 列 × 每腿一行（0 腿时只有表头） | `trial_id`、`group`、`segment`、`entry_date`、`exit_date`、`direction`、`data_source`、`reason`、`q`、`notional`、`pnl_bp`、`cons_pnl_bp`、`commission`/`stamp`/`transfer`/`slippage`/`impact`、`participation_pct`、`exec_anomaly`、`prior_anomaly`、`hold_bars`、`mae_bp`、`theta`/`sigma`/`dev`/`vr` |

phase 命名：`training_1…training_5`（其中 `training_final` 为第 5 个训练窗）、`evaluation_1…4`、`holdout`、`sensitivity_train`。
`trial_id` 形态 `phase/candidate`，主候选名 `selected_A` / `selected_B`；敏感性候选名 `p8_primary`、`p8_notional_10000`、`p8_commission_0.0003`。
**R 对照（RLeg）不落盘**：`sim.RLeg` 只挂在 `exp.Observed.control` 上，供 `judgement` 算 P5；`trials.csv`/`legs.csv` 无对照列（详见 §3）。

## 1. P1–P10 字段映射

| 判据 | 方案 §8.3 判定动作 | `summary.json` 路径 | `trials.csv` | `legs.csv` | 预检说明 |
|---|---|---|---|---|---|
| P1 | 每评估折+保留集 n ≥ 30 且覆盖 ≥ 20 交易日 | `criteria.P1.windows[]`（5 个：fold1–4 + holdout，各含 `n`/`days`/`mean`/`low`/`high`）、`criteria.P1.status` | 对应 `phase=evaluation_1..4`、`holdout` 的 `selected_A` 行 `n`、`mean_bp`、`ci_low_bp`、`ci_high_bp` | `holdout/selected_A` 行数 = 保留集腿数 | 阈值在 runner `config.yaml`：`grid.min_legs_select`、`stats.min_cover_days`（summary 不含配置，需与方案/配置核对） |
| P2 | 保留集均值 > 0、下限 > 0；4 折至少 3 折 > 0；robustness 同号 | `criteria.P2.status`、`criteria.P2.robustness`；`criteria.P1.windows[-1]`（保留集 mean/low）；`holdout_by_source` | 各 `phase=evaluation_*` `selected=True` 行 `mean_bp` | 保留集腿 `pnl_bp` | robustness=0.6×median(折均值)+0.4×min（可复算）；保留集 low 来自 P1.windows[-1].low |
| P3 | 保留集均值 > 2×平均往返成本 | `criteria.P3.status`、`criteria.P3.average_cost_bp` | `holdout/selected_A` 的 `mean_bp` | `holdout/selected_A` 腿：`(commission+stamp+transfer+slippage+impact)/notional*1e4` 取均值 | 门槛倍率 `stats.edge_cost_mult_p3`（config）；平均成本可用 legs 复算，应与 `average_cost_bp` 一致 |
| P4 | 时间止损∪收盘未了结∪无法估值 ≤ 30% | `criteria.P4.status`、`criteria.P4.share` | 无 | `holdout/selected_A` 腿 `reason ∈ {time, deferred, unvaluable_*}` 占比 | 阈值 `stats.max_bad_exit_share`（config） |
| P5 | A*−R 配对差 > 0、区间下限 > 0 | `criteria.P5.status`、`criteria.P5.paired.{n,days,mean,low,high}` | `holdout/selected_A`.`n`（对照腿数 1:1） | 保留集腿数（与 paired.n 比对） | 逐腿对照值未落盘 → 见 §3；`paired.n` 必须等于保留集腿数 |
| P6 | A* 邻域无符号翻转、不低于一半 | `criteria.P6.status`、`criteria.P6.neighbors[]`（邻域 mean_bp 列表，首元素为 A*） | `phase=training_final` 中按 `params` 网格取 A* 邻域行的 `mean_bp` | 无 | 邻域=参数网格 ±1 步（`exp._neighbors`）；完整性校验 `all(x>0 and x>=values[0]/2)` |
| P7 | 两环境标签都出现且各自不显著为负 | `criteria.P7.status`、`criteria.P7.labels`、`criteria.P7.scores.{up,down}.{n,days,mean,low,high}` | 无（标签由沪深300日线定） | `holdout`+`evaluation_*` 腿按年合并 | 2023-10-18 起按自然年标签；两标签缺一 → unknown 上报 |
| P8 | 训练窗口求 X、Y；保留集验 1 万/0.03% 档 > 0 | `criteria.P8.status`、`criteria.P8.sensitivities.{p8_notional_10000,p8_commission_0.0003}.{train,holdout}`、`training_brackets`、`boundary` | `phase=sensitivity_train`（train 列）与 `phase=holdout`（holdout 列）的 `mean_bp`，候选名同上 | 对应 `trial_id` 的 `pnl_bp` | X/Y 边界在 `training_scope`/`boundary`；P8 不是通过条件（口径见方案 §8.3） |
| P9 | 退市股核验全过 | `criteria.P9.{status,state,...}`、`delisting.{state,official_count,missing,missing_share,tail_missing,period_unknown,pass_with_period,no_delisting_period_by_rule,no_delisting_period_evidence_only,suspended_until_delisting,no_period_policy}` | 无 | `entry_date`/`exit_date` | T-A155 四分类；`missing`/`tail_missing` 非空即 fail，`period_unknown` 非空即 unknown |
| P10 | 训练窗口定方向：某方向 ≤ 0 不启用 | `criteria.P10.status`、`criteria.P10.directions` | `training_final` 选中行 `params.directions`（JSON 内） | 腿 `direction` 分布 | directions 为空 → fail（无方向可选） |

## 2. 红旗 R0–R14 检测位置

| # | 检测对象 | 路径/字段 | 预检脚本可自动判 |
|---|---|---|---|
| R0 | L1–L14 任一 fail | `checks.L1…L14`（`status`/`state` 为 fail/blocked）、`checks.bar_quality` | 是（结构判定） |
| R1 | 折均值单调递增且保留集回落 | `trials.csv` 各 `evaluation_*` selected 行 `mean_bp`；`holdout_by_source` | 部分（趋势/符号） |
| R2 | R 组均值 ≥ 0 / 成本项为 0 / 1 万档不低于 5 万档 | `criteria.P5.paired` + 腿成本列 + `criteria.P8.sensitivities` | 部分（见 §3） |
| R3 | 保留集两段符号相反或差距 > 3× | `holdout_by_source.through_2026-08-06` vs `from_2026-08-07`（`n`/`mean`） | 是 |
| R4 | 2026-04-13 前后不可成交/容量行为跳变 | `exclusions.<year>.<reason>` 按年计数（含 `suspended`、`new_listing`、`daily_anchor_outside_coverage`） | 部分（按年占比对比） |
| R5 | 印花税未分段 | 腿 `stamp`/`notional`，按 `exit_date` 分 ≤2023-08-27 / ≥2023-08-28 | 是 |
| R6 | 触发率 <0.01% 或 >20%；A 普遍负而 B 普遍正 | 腿数/有效股票日（`checks.L9.stock_days`、`exclusions`）；`trials.csv` group=A/B 的 `mean_bp` | 部分（触发率近似） |
| R7 | T+1 / 底仓逻辑 | 腿 `direction`、`prior_anomaly`、`q`/`entry_date`/`exit_date` | 部分（只能看方向与异常标记） |
| R8 | 不可成交率 = 0 或 >30% | `checks.L13`、腿 `participation_pct`/`exec_anomaly` | 部分（腿部异常标记） |
| R9 | 时间止损率 >50% 且均值 ≈0 | 腿 `reason=time` 占比；`holdout` 腿 `mean_bp` | 是 |
| R10 | 评估折参与选参 / embargo 入场 / 了结越段 | `trials.csv` `holm_family`=False 的 selected 行、`segment`/`start`/`end`；腿 `exit_date` vs `summary.segments.<seg>.end` | 是（越段/embargo） |
| R11 | P9 fail / 尾段缺失占比高 | `criteria.P9`、`delisting` | 是 |
| R12 | 无法估值率 >15%；除权日涨跌停偏移 | 腿 `reason=unvaluable_*` 占比；`checks.L12.unvaluable_legs`、`checks.L12.reference_checks` | 是（率） |
| R13 | R 组与 A* 不 1:1 / 分布严重不对称 | `criteria.P5.paired.n` vs 保留集腿数；R 分布未落盘 | 部分（1:1 可判） |
| R14 | ST 不明剔除 = 0% 且数据源未就绪 | `coverage.by_exchange_year[].st_known_share`、`data.st_coverage`、`exclusions` `st_unknown` | 是 |

## 3. 非持久化字段与替代（重要）

**R 组（随机对照）逐腿数值没有落盘。** `sim.simulate_random` 返回的 `RLeg{mean_bp,n_ok}` 只存在于
`exp.Observed.control`，`judgement.evaluate` 用它算 `criteria.P5.paired` 后即丢弃；`legs.csv`/`trials.csv` 都没有对照列。
因此出数后能做的 R 组判据只有：

1. **1:1 对应**：`criteria.P5.paired.n` 必须等于 `holdout/selected_A` 的腿数（多/少 → R13）。
2. **配对差**：`criteria.P5.paired.{mean,low,high}`（P5 的显著性就是该区间下限 > 0）。
3. **R 组均值反推**：`implied_R_mean ≈ A*_holdout_mean − P5.paired.mean`；框架预期 ≈ −30 bp，若 ≥0 → R2/R13 嫌疑。
4. **分布对称性 / 逐腿配对 t 检验：无法从现有产物复算**；如判读需要，须后端在 `legs.csv` 增 `control_mean_bp`/`control_n_ok`
   两列（或单独 `controls.csv`）——本单不改 runner，只在报告里按现有字段判。

## 4. 预检脚本

`docs/strategies/T-R59/prescreen.py`（纯标准库，无第三方依赖）：

```bash
python docs/strategies/T-R59/prescreen.py \
  --summary <run>/summary.json --trials <run>/trials.csv --legs <run>/legs.csv \
  [--out prescreen.json]
```

输出（JSON + 一屏摘要）：P1–P10 状态快照、R0–R14 可自动判项、R 组反推、数据质量（ST/上市状态覆盖、剔除计数）、
以及「无法判定/需人工」清单。0 腿运行时全部标 `no_legs` 而不是报错（T-R64 空结果可直接过）。
