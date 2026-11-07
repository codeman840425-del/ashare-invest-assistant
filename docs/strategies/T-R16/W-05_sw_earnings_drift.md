# W-05 业绩预告漂移 `sw_earnings_drift` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/W-05.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `sw_earnings_drift`；category `event`；horizons `[swing]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：业绩大幅超预期的公告发布后，市场反应不足，价格在公告后数周持续漂移（盈余公告后漂移，PEAD 类现象；本卡没有引用核实过的文献）。
- falsified_by：1) PIT 门禁关闭后，按公告可见时点对齐的样本外 20 日扣费超额中位数 ≤ 0；2) 把公告当日就可交易的样本剔除后，结论消失（说明存在前视）；3) 超预期幅度分档之间收益不单调。
- 维度：fundamental 和 news 为 core（事件）；technical 为 auxiliary；news 风险由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 250 日。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.np_yoy_latest | 事件 | pct（30 = 30%） | — | plrq 次日 09:30 | declared；**PIT 门禁未关闭**（DAT-2） |
| 公告日锚点 `days_since_ann`（拟议，ENG-6） | 日 | count | — | — | 不存在 |
| f.ma_trend | 日 | pct | qfq | T 盘后 | 已注册 |
| f.close_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
预热：60 根有效日 K（ma_trend）；不足时 `insufficient_data`，不产生候选。数据缺失：`f.np_yoy_latest` 为 null → `KEY_DATA_MISSING`，不得用上一期数据替代。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.np_yoy_latest >= p.yoy_min` | 只用公告日 ≤ as_of 的值，可见时点 = 公告次日 09:30 |
| E2（拟议） | entry | `days_since_ann <= p.entry_window` | 只在公告后 N 日内入场，ENG-6 |
| E3 | entry | `f.ma_trend > 0` | MA20 > MA60（单位 pct） |
| C1 | counter | `f.momentum_60d > p.overext` | 公告前已大幅上涨，属于预期内 |
| I1 | invalidation | `f.close_qfq < plan.entry_price_qfq * (1 - p.fail_pct) within 3 days` | 公告后价格反应为负 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 原稿 `ctx.last_price <= plan.stop_loss` 口径混用，已改 |
| X2 | exit | `f.ma_trend < 0` |  |
| X3 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |

## 8–10 执行与仓位
公告次日盘后确认，下一交易日开盘模拟入场（不在公告当日追入）；仓位按 RC2。

## 11 验证（本轮不写 golden）
门禁关闭前只做 `fixture` 和 `post_close_stats`；关闭后做事件研究（以公告可见时点为 0 日），`min_n=30`。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
不依赖 G-02；downtrend 时只提示（hypothesis）。节奏：每日盘后。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 L-02 同为基本面驱动，并列展示。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| yoy_min | float | 30.0 | 15.0 | 100.0 | 5.0 |
| entry_window | int | 3 | 1 | 5 | 1 |
| overext | float | 40.0 | 20.0 | 80.0 | 5.0 |
| fail_pct | float | 0.03 | 0.01 | 0.05 | 0.01 |
| stop_pct | float | 0.08 | 0.05 | 0.12 | 0.01 |
| max_hold | int | 15 | 10 | 40 | 5 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- DAT-2 PIT 门禁
- ENG-6 事件时间锚点（公告后天数）

## 复核记录（相对 DeepSeek 原稿）
1. 原稿“超预期”没有可用的一致预期数据，已改为同比阈值，并在反证中说明
2. 原稿把执行层锁定写成入场条件，已移出
3. 原稿 `ctx.holding_days == 0` 的写法没有意义，已改为 I1
4. 原稿把行业 RS 转负作为 weakening，依赖 DAT-3，已删除
5. momentum 单位已改为 pct
