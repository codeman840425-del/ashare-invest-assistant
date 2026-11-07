# S-03 涨停接力 `st_limitup_relay` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/S-03.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `st_limitup_relay`；category `momentum`；horizons `[short]`；risk_level `high`。plan 2.5.11 中的同类高风险模板 key 为 `st_strong_momo`（默认不启用、不被分类器推荐），**key 是否统一待定**；本卡沿用 risk_level high 与默认不启用。

## 3 假设、反证与维度
- why_it_works（hypothesis）：连板股在市场情绪较好时，封板强度可以延续到次日溢价；这是情绪驱动，风险高。
- falsified_by：1) 样本外次日开盘溢价扣费后中位数 ≤ 0；2) 把一字买不进的样本计入后结论翻转（说明存在幸存者偏差）；3) 市场宽度分档之间结论不单调。
- 维度：sentiment 为 core（连板与市场宽度）；technical 为 auxiliary；sector_market 为 veto；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板（不同板块涨跌幅不同，连板含义不同，需分板块统计）；上市满 60 日；ST 由 G-01 排除。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.is_limit_up_close / f.limit_up_count_20d | 日 | bool / count | none | T 盘后 | 已注册 |
| f.market_breadth | 日 | ratio | none | T 15:05 后 | 已注册 |
| 封单额、开板次数（拟议，FEA-4） | 日 | CNY / count | none | T 盘后 | 未注册，来源未知 |
| 涨停股池（DAT-5） | 日 | — | — | — | plan G-02 提及，未实测 |
预热：20 根有效日 K；不足时 `insufficient_data`，不产生候选。数据缺失：市场宽度缺失 → 买入方向 `KEY_DATA_MISSING`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.is_limit_up_close == true and f.limit_up_count_20d >= p.min_boards and f.limit_up_count_20d <= p.max_boards` | 连板区间；`limit_up_count_20d` 不等于连续板数，“连续”需要 `for N days` 表达，见下方说明 |
| E2 | entry | `f.market_breadth >= p.breadth_min` |  |
| V1 | veto | `f.market_regime == 'downtrend'` |  |
| C1 | counter | `f.amount > f.amount_20d_avg * p.vol_spike` | 高位放巨量，可能是分歧出货 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 日线收盘价判断 |
| X2 | exit | `f.is_limit_up_close == false` | 次日没有封板即离场（接力逻辑失效） |
| X3 | exit | `f.market_breadth < p.breadth_exit` |  |
| X4 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |
- 连续板数：`f.is_limit_up_close == true for p.min_boards days` 可以表达“至少 N 连板”，但参数化的 N 需要 `for p.x days`（plan W-01 缺口③），**待定**。
- 原稿的盘中观察窗 09:35–09:45 与 `ctx.last_price` 需要分钟数据（DAT-1），已删除；本卡只做日线收盘确认、次日开盘模拟入场。
- 次日一字开盘买不进 → `LIMIT_LOCKED(buy)`，必须计入统计，不能剔除。

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘价模拟入场；一字涨停记 `LIMIT_LOCKED` 并计入偏差统计；单票仓位按 RC2 建议，高风险模板默认不启用。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`（含买不进样本）、`tracking_sim`；horizon_days [1,3]；`min_n=30`；按板块分组统计。

## 14 不可执行原因
`LIMIT_LOCKED`（buy 和 sell 两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
只用于 uptrend 且市场宽度高的环境；节奏：每日盘后扫描。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 S-04（断板反包）在同一标的同日互斥：S-03 要求当日封板，S-04 要求前日断板。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| min_boards | int | 2 | 1 | 3 | 1 |
| max_boards | int | 4 | 3 | 6 | 1 |
| breadth_min | float | 0.45 | 0.3 | 0.6 | 0.05 |
| breadth_exit | float | 0.35 | 0.2 | 0.5 | 0.05 |
| vol_spike | float | 3.0 | 2.0 | 5.0 | 0.5 |
| stop_pct | float | 0.05 | 0.03 | 0.1 | 0.01 |
| max_hold | int | 3 | 1 | 5 | 1 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- FEA-4 封单额、开板次数（未注册）
- DAT-5 涨停股池来源
- RUL-6 `for p.x days` 参数化（plan W-01 缺口③）
- RUL-7 key 与 plan `st_strong_momo` 是否统一

## 复核记录（相对 DeepSeek 原稿）
1. 原稿把 `limit_up_count_20d` 当作连板数，二者含义不同，已改正
2. 原稿盘中窗口依赖分钟数据，已删除
3. 原稿把“一字板不可买”标成 not_triggered，已改为 `LIMIT_LOCKED` 并计入偏差
4. 原稿冲高回落止盈用 `ctx.last_price` 与 qfq 混用，已删除
5. 标注与 plan 中 S-03 key 不一致
6. 原稿仓位、并发参数属于 RC 层，已删除
