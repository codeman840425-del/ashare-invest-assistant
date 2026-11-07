# T-03 开盘缺口回补T `t_open_gap` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/T-03.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `t_open_gap`；category `intraday_t`；horizons `[intraday_t]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：开盘相对前收显著跳空、且早盘不能延续时，价格有向前收方向回补的倾向；用底仓做缺口方向的反向T。
- falsified_by：1) 盘后统计中，缺口在 14:50 前回补到目标带的比例不高于同幅度缺口的历史基线；2) 扣费后单腿结果中位数 ≤ 0；3) 缺口幅度分档（0.8%、1.5%、3%）之间结论符号不一致。
- 维度：technical 为 core；sector_market 为 veto（G-02 判 downtrend 时不做 buy_first）；news 由 N-01 系统挂载（隔夜公告导致的缺口不做，见 C1）。

## 4 标的范围
持有合规可卖底仓的主板、创业板、科创板证券；上市前 5 日无涨跌幅限制的新股不做。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.open_qfq（拟议，FEA-1） | 日（09:25 后） | 元 | qfq@as_of | T 日 09:25 集合竞价后 | 未注册；开盘快照延迟未实测 |
| f.close_qfq | 日 | 元 | qfq@as_of | T−1 盘后（作为前收） | 已注册 |
| f.vwap_intraday / f.vwap_dev / f.intraday_sigma | 盘中 1m | 元 / ratio / ratio | none（当日） | 本 bar 结束后 | 已注册；1 分钟历史覆盖未核实（DAT-1） |
| f.limit_up_price / f.limit_down_price | 日 | 元 | none | T 日盘前 | market_rules 计算 |
预热：前收 1 根 + 开盘后 `p.wait_bars` 根 1 分钟 bar；不足时 `insufficient_data`，不产生候选。数据缺失：`f.open_qfq` 未注册，所以本卡在设计上不可求值；快照缺失 → `DATA_STALE`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry（sell_first，向上缺口） | `f.open_qfq >= ref(f.close_qfq, 1) * (1 + p.g_min) and f.open_qfq <= ref(f.close_qfq, 1) * (1 + p.g_max)` | 缺口幅度在区间内；`ref` 跨日、盘中混用的口径见 RUL-4 |
| E2 | entry（buy_first，向下缺口） | `f.open_qfq <= ref(f.close_qfq, 1) * (1 - p.g_min) and f.open_qfq >= ref(f.close_qfq, 1) * (1 - p.g_max)` | 需有等量可卖旧股用于当日回补 |
| E3 | entry | `f.vwap_dev <= p.vwap_confirm` | 向上缺口：开盘 `p.wait_bars` 分钟后价格不高于 VWAP，确认没有延续（向下缺口取反） |
| C1 | counter | `f.ann_risk_count_10d > 0` | 有隔夜公告的缺口不视为情绪缺口（N-01 另行否决） |
| I1 | invalidation | `f.open_qfq >= ref(f.close_qfq, 1) * (1 + p.g_max)` | 缺口过大，视为事件驱动 |
| X1 | exit（回补） | `between(f.vwap_dev, -p.target_band, p.target_band)` | 回到 VWAP 附近回补 |
| X2 | exit（止损） | `f.vwap_dev >= p.stop_dev` | 向上缺口继续扩大时止损（向下缺口对称） |
| X-T | exit（时间） | `ctx.now_hhmm >= p.time_stop_hhmm` | 日终了结 |

## 8–10 执行与仓位
T 腿数量 ≤ `p.t_ratio` × `ctx.sellable_qty`，按整手规则取整；同一证券每天最多 `p.max_t_per_day` 次；一笔 T 结束后持仓数量回到原值，不新增净敞口。日终未回补的腿按 X-T 了结（规则设计；执行配对见 ENG-1）。

## 11 验证（本轮不写 golden）
方法 `fixture`、`trigger_stats` + 盘后重放：触发后回补率、单腿扣费后结果、日终未回补率，均以 `Stat` 输出并标“模拟”；时间切分样本外，`min_n=30`。

## 14 不可执行原因
`NO_POSITION`、`T1_NOT_SELLABLE`、`LIMIT_LOCKED`（buy 或 sell 方向）、`SUSPENDED`、`DATA_STALE`、`NON_TRADING_TIME`；盘后统计模式下只做统计，不产生不可执行原因。

## 15–16 环境与节奏
适用于 range；趋势日（G-02 判单边）不做逆势T。节奏：盘后重放统计。

## 17 A股约束
**做T约束**：只用 T−1 日及以前形成的合规可卖底仓（`ctx.sellable_qty > 0`）；严禁当日新买入的股份当日卖出，也不为了做T当日开新仓；两腿配对语义（ENG-1）未实现，**两腿未配对时不可执行**，只能 `post_close_stats`。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 T-01、T-02 同日同证券只记一次T（ENG-1）。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| g_min | float | 0.008 | 0.005 | 0.015 | 0.001 |
| g_max | float | 0.03 | 0.02 | 0.05 | 0.005 |
| wait_bars | int | 10 | 5 | 15 | 1 |
| vwap_confirm | float | 0.0 | -0.005 | 0.005 | 0.001 |
| target_band | float | 0.002 | 0.001 | 0.005 | 0.001 |
| stop_dev | float | 0.015 | 0.01 | 0.03 | 0.005 |
| t_ratio | float | 0.3 | 0.1 | 0.5 | 0.05 |
| max_t_per_day | int | 1 | 1 | 2 | 1 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |
| time_stop_hhmm | 待定（RUL-2） | 14:50 | — | — | — |

## 23 当前不可导入原因与引擎需补能力
- ENG-1 两腿配对（未配对时不可执行）
- ENG-2 入场条件中引用 ctx 字段
- ENG-4 盘中实时求值（C(5) 条件满足前只做盘后统计）
- RUL-2 时刻类参数类型
- RUL-4 盘中 `ref`、`for N bars` 的粒度（bar 还是 day）
- FEA-1 `f.open_qfq`（未注册，拟议）
- DAT-1 1 分钟覆盖
- DAT-6 开盘快照延迟实测

## 复核记录（相对 DeepSeek 原稿）
1. 原稿把 `f.open_qfq` 写成“已可用”，已改为拟议（FEA-1）
2. 原稿止损用百分比，与 vwap_dev（ratio）的口径已统一
3. 原稿把一字锁定写进 counter，已改为执行层原因
4. 原稿 sector_market 写成同时否决 uptrend 和 downtrend，已改为只禁止逆势方向
