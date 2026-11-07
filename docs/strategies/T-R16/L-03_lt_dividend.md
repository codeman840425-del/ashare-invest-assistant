# L-03 红利低估 `lt_dividend` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/L-03.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `lt_dividend`；category `dividend`；horizons `[long]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：高股息、低估值、现金流稳定的公司提供防御性收益；股息是核心变量。
- falsified_by：1) 股息率特征登记、PIT 门禁关闭后，样本外高股息组相对全市场的 12 个月扣费超额 ≤ 0；2) 高股息组的次年分红削减率显著高于全市场（股息陷阱）；3) 剔除银行后结论翻转。
- 维度：fundamental 为 core；technical 为 auxiliary；news 由 N-01 系统挂载。

## 4 标的范围
全 A（不含北交所）；上市满 250 日。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| 股息率 TTM（拟议，FEA-3） | 事件 | pct | — | 分红公告日 | **未注册**，没有这个特征本卡不成立 |
| f.pe_ttm_pit_ind_pct | 日 | 0–1 | — | T 盘后 | declared（DAT-2） |
| f.ocf_to_np_ttm_pit / f.roe_ttm_pit / f.debt_ratio_pit | 季 | ratio / pct / ratio | — | 公告日 | declared |
预热：同 L-01；不足时 `insufficient_data`，不产生候选。数据缺失：股息率未注册 → 本卡在设计上不可求值；其余同 L-02。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1（拟议） | entry | `f.div_yield_ttm_pit >= p.dy_min` | FEA-3 |
| E2 | entry | `f.pe_ttm_pit_ind_pct <= p.val_pct` |  |
| E3 | entry | `f.ocf_to_np_ttm_pit >= p.ocf_min` |  |
| E4 | entry | `f.roe_ttm_pit >= p.roe_min` | 原稿写 0.08，单位应为 pct 8 |
| F1 | filter | `f.debt_ratio_pit <= p.debt_max` | 银行和保险为 null 时见 RUL-1 |
| C1 | counter | `f.np_yoy_latest < p.np_drop` | 利润大幅下滑，可能削减分红 |
| I1 | invalidation | `f.pe_ttm_pit_ind_pct >= p.val_exit` |  |
| X1 | exit（止损） | `f.close_qfq <= ctx.cost_price_qfq * (1 - p.stop_pct)` |  |
| X2（拟议） | exit | `f.div_yield_ttm_pit < p.dy_exit` |  |
| X3 | exit | `f.ocf_to_np_ttm_pit < p.ocf_exit` |  |
- 原稿 `f.ma_trend != "downtrend"`：ma_trend 是 pct 数值，不是枚举，已删除。
- 除权：qfq@as_of 价格已包含分红调整，股息率本身按不复权价格计算（FEA-3 定义待定）。

## 8–10 执行与仓位
每月第一个交易日盘后出 screen，次日开盘模拟成交；等权，单票上限按 RC2；行业上限与 top-N 属于组合层（ENG-3，拟议）。

## 11 验证（本轮不写 golden）
同 L-02；另需统计次年分红削减率。

## 14 不可执行原因
`KEY_DATA_MISSING`（PIT 字段为 null 或门禁未关闭）、`SUSPENDED`、`LIMIT_LOCKED`（sell 方向写 direction）、`T1_NOT_SELLABLE`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
偏防御，不依赖择时；月度节奏。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 L-01 低估值可能重叠（去重属于 ENG-3）。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| dy_min | float | 4.0 | 2.0 | 7.0 | 0.5 |
| dy_exit | float | 2.5 | 1.0 | 4.0 | 0.5 |
| val_pct | float | 0.3 | 0.1 | 0.5 | 0.05 |
| val_exit | float | 0.7 | 0.5 | 0.9 | 0.05 |
| ocf_min | float | 0.8 | 0.5 | 1.2 | 0.1 |
| ocf_exit | float | 0.5 | 0.3 | 0.8 | 0.1 |
| roe_min | float | 8.0 | 5.0 | 15.0 | 1.0 |
| debt_max | float | 0.7 | 0.5 | 0.9 | 0.05 |
| np_drop | float | -30.0 | -60.0 | -10.0 | 5.0 |
| stop_pct | float | 0.2 | 0.1 | 0.3 | 0.05 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- FEA-3 股息率 TTM（未注册）
- DAT-2 PIT 门禁
- ENG-3 组合层
- RUL-1 null 放行语义

## 复核记录（相对 DeepSeek 原稿）
1. ROE 单位已改正
2. ma_trend 被误当作枚举，已改正
3. 原稿把可交易性和锁定写进入场条件，已移出
4. 股息率字段标为拟议，未当作现有能力
