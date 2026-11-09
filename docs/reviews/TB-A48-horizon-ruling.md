# TB-A48 裁定：H-01 多周期口径（架构师，北京 2026-11-09）

> 状态：裁定生效（架构师默认，用户可否决）。基线 251b4cb。本文只定口径，不改实现；实现项见 §5 影响清单，转 Chief 派单。
> DeepSeek：未用，原因：裁定结论不外包。

## 0. 问题

P2N-R10 体检确认：H-01 `hold_risk_monitor` v1/v2 声明 `horizons: [intraday_t, short, swing, long]`（四周期通用持仓风控），无唯一版本周期；而三处消费点只要单值：
1. `strategy_instances.horizon` 单列（plan 3.3）——系统挂载 H-01 实例时必须写一个值；
2. 候选信号/建议结论 `horizon` 单值（`signals/service.py` 取 `instance.horizon`）；
3. RC5 模拟失败计数回退链第二级"策略版本声明的周期"（契约 §7.11.3 T-A33 第 2 点）对多周期版本无解。

R10 已声明不自行强选，留架构师明确语义。本裁定即该语义。

## 1. 既有权威条款（依据）

| 条款 | 出处 |
|---|---|
| horizon 枚举 `intraday_t / short / swing / long` | plan §2.5.0 字段表（L602）；契约 §3 |
| H-01 是"周期分类只推荐、不自动启用"的唯一例外；每只持仓一个系统实例（`origin=system, status=active`） | plan §2.5.11A（L903/905）、§9 问题 15、C(3) |
| H-01 与 G-01/G-02/N-01 是**跨周期系统组件** | plan §2.5.11A（L894） |
| RC5 跟踪期映射：`intraday_t`→1、`short`→5、`swing`/`long`→20（取不短于典型持有期的最长可用跟踪期） | T-A36（用户选 B）+ T-A37 修正；plan L780；契约 §7.11.3 第 2 点 |
| 回退链：结论 horizon → 版本声明周期 → 仍不清楚跳过 + `sim_fail_horizon_unknown`，不默认 5 日 | 契约 §7.11.3 T-A33 第 2 点 |
| 多值数组第一个不当默认；不凭扫描频率/MA 窗口/证伪指标改卡片周期 | `docs/strategies/P2N-R10/README.md` |
| H-01 卡片证伪口径三处均为 20 日 | `cards/hold_risk_monitor.md` §反证/失效、hypothesis.falsified_by |
| 卡片版本不可变；改内容须递增 version_no | plan §2.5.13/2.5.14 |

## 2. 裁定

### R1｜H-01 系统实例挂载周期 = `swing`

- `attach_system` 及未来一切挂载调用方传 `horizon="swing"`（∈ 卡片 `horizons[]`，通过现行 I3 等价校验；挂载幂等键不变：user × account × security × `origin=system` 一只一份）。
- 理由：
  1. **必须单值且必须合法**：表列与契约实例对象都是单枚举；不可 null、不可多值、不可"每周期一个实例"（后者重复信号、虚增观测、违反"每只持仓一个系统实例"）。
  2. **与卡片自身证伪口径同窗**：H-01 v2 的证伪条款三处全用 20 个交易日（exit_signal 后 20 日收益、MA60 跌破后 20 日超额）；20 日 = T-A37 映射中 swing/long 的跟踪期。挂 swing 后 RC5 失败计数窗口与卡片研究证伪窗口一致，不需新研究。
  3. **语义归类**：H-01 规则本体是 MA60 趋势/ATR 缓冲型"转弱"预警，预警时标为多日—数周；long 定义"半年以上"会把风控信号计入中长线策略统计，short/intraday_t（1/5 日）会让连亏计数被证伪窗口外的短噪声触发。swing（数周–数月）是四档中最接近的档位。
- **不改卡片**：`horizons` 保持四值不动（H-01 的风险预警对任何持有意图的持仓都成立；把卡片限成 [swing] 会让其他周期持仓失去挂载资格）。卡片层"四周期适用"、实例层"单值档位"是两层语义，不冲突，符合版本不可变规则——**不为此出 v3**。

### R2｜已存在的系统实例不回溯改写

已挂的系统实例（管理员/测试账户若已挂）维持原 horizon，其后续信号沿用实例值；不批量 UPDATE、不重算历史。只有新挂载按 R1。用户暂停/恢复不改变实例 horizon。

### R3｜RC5 回退链对多周期版本的终局语义

- 回退链第二级"策略版本声明的周期"**仅在版本声明唯一周期时可解析**。多周期版本（`horizons` 长度 > 1，含 H-01 v1/v2）该级**不可解析**：结论缺 horizon 的观测保持跳过 + gap `sim_fail_horizon_unknown`，**不得**用 R1 的 swing 回填、不得取数组首元素。
- `simulated_failures(version_horizon=…)` 的生产者对多周期版本必须传 `None`（现行实现 `row.horizon or version_horizon → None ∉ mapping → gap` 已符合；本条把"必须传 None"定为口径，防止未来接线者塞固定值）。
- 理由：结论缺 horizon 说明结论生成不完整，硬套默认会悄悄改变失败计数窗口且不留痕；gap 保留可观测性，与 T-A33"不默认 5 日"、R10"未知不默认"同向。
- 覆盖范围：正常路径不会触发——信号从实例产生必带 `instance.horizon`（=swing）；gap 只覆盖历史/异常结论与 receipt 缺字段的防御路径。

### R4｜信号、结论与统计的落点

- H-01 候选信号与建议结论 `horizon` = 实例 horizon（R1 后即 swing）；前端照常按返回值展示周期标签，纯离场单元格"离场 x/y"展示不变，无特殊分支。
- `suggestion_tracking` 三窗口（1/5/20）照常全算，不因 R1 改变（跟踪与 RC5 计数是两个机制：前者三窗口全观测，后者只按 T-A36 映射窗口计失败）。
- `strategy_tracking_stats` 的 H-01 统计行自然落 `horizon=swing` 分组，无代码改动。

### R5｜valid_until 例外

plan §2.5.8 的 valid_until 周期默认（波段 5 个交易日）**不适用**于 H-01：卡片 v2 显式配置 `valid_until: {trading_days: 1}`，模板配置优先，维持 1 个交易日。实现不得因实例挂 swing 套用 5 日默认。

### R6｜catalog 其余多周期条目本轮不处理

R10 清单中其余 6 条多值记录（G-01/G-02/H-01/N-01/N-02/N-03 目录条目）维持原声明。G-01/G-02/N-01 按 plan §2.5.11A 以 gate/veto/上下文组件挂载，不产生带 horizon 的策略结论，无实例单值问题。若未来制成正式卡，须先由权威规格定唯一版本周期或结论绑定语义，另走裁定，不沿用 R1。

## 3. 例外汇总

| 例外 | 内容 |
|---|---|
| 已存实例 | 不回溯改写（R2） |
| 多周期版本 RC5 | 第二级回退不可解析，保持 gap，不回填 swing（R3） |
| valid_until | 卡片显式 1 交易日优先于周期默认 5 日（R5） |
| 卡片 horizons | 保持四值；不因实例单值出 v3（R1） |
| 研究参数漂移 | 未来卡片证伪窗口若改档，RC5 映射仍按 T-A36（swing→20），两者允许不同、各归各版本 |

## 4. 不兼容点

无。契约字段、枚举、表结构、状态机均不变；全部为实现层口径约定。

## 5. 影响清单（实现项，转 Chief 派单）

| # | 影响 | 角色 | 动作 |
|---|---|---|---|
| 1 | H-01 挂载接线（未来 T-B30/挂载 hook/运维编排）传 `horizon="swing"` | 后端 | 新挂载调用点按 R1；当前无调用点，无即时代码改动 |
| 2 | RC5 receipt 生产链（P2N-08 剩余）对多周期版本 `version_horizon=None` | 后端 | P2N-08 恢复派单的验收加一条定点用例：H-01 结论缺 horizon → gap `sim_fail_horizon_unknown`，不回填 |
| 3 | plan §2.5.11A H-01 行、契约 §7.11.3 T-A33 第 2 点各补一句挂载周期=swing、多周期版本第二级不可解析 | 架构师 | 约 2 行文档同步，另派执行（本文先生效） |
| 4 | P2N-09 解释、前端、T+1/5/20 跟踪 | — | 无改动（R4） |
| 5 | 研究员卡片 | 研究员 | 无改动；不建 v3、不改证伪窗口 |

## 6. 验收口径（供后续定点测试引用）

- 挂载：`attach_system(..., horizon="swing")` 成功；`horizon="short"` 亦合法（∈ horizons）但按本裁定不得使用；幂等不重复建。
- RC5：四周期版本 + 结论无 horizon 的观测 → 跳过、gap=`sim_fail_horizon_unknown`、不清零；`version_horizon` 传 `None`。
- 信号：H-01 信号 horizon=实例值；valid_until=1 个交易日。
