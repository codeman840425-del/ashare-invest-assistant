# T-A74 裁定与评审：H-01 版本、T-R35 待裁阈值、T-R34 评审（架构师，2026-11-09 America/Denver）

> 基线 origin/main=8e847d5。只定口径、不改实现；不改 docs/strategies（研究员负责）。
> 第 ① 项（G7 代批相关修订：plan.md:996、plan.md:3628、契约 T-A18/T-A20）**待用户本人确认，本文未修订、不裁定**；T-R35 §5 第 1 条「G7 代批效力」同样不在本文范围。
> 评审对象：strat/T-R35=7695fd0（docs/strategies/T-R35/README.md、metrics_slots.json）；strat/T-R34=cf81d1e。

## 1. ②(a) H-01 跨四周期、缺 horizon：**不拆版本**

**结论**：维持 H-01 v2 单一版本、`horizons` 四值不变，不出 v3、不按周期拆成多个版本或多个实例。TB-A48 R1–R4 继续有效，本文只补「计数」口径。

**依据**
| 依据 | 出处 |
|---|---|
| H-01 v2 声明四周期；证伪口径为 20 个交易日；`valid_until` 1 个交易日 | docs/strategies/cards/hold_risk_monitor.md:35、42、97、117 |
| 已裁：卡片保持四值、不为实例单值出 v3；实例挂载 `swing`；多周期版本 RC5 第二级回退不可解析，缺 horizon 保持 gap，不回填 swing、不取首元素 | docs/reviews/TB-A48-horizon-ruling.md:30-37、43-48；plan.md:907；api-contract.md:1280 |
| 每只持仓**一个**系统实例，`horizon=swing` | plan.md:903 |
| 晋级门槛清单 M-01、M-03、M-04、M-08 已覆盖上述口径 | docs/strategies/card_promotion_gates.md:196、198、199、203 |
| 统计按「版本 × 周期 × 范围 × 跟踪期」分组 | plan.md:785 |
| 发布门槛按版本计：n ≥ 20 或满 20 个交易日，且 `verified_live`，且管理员批准 | plan.md:959；T-A14 plan.md:970-973 |
| 卡片版本不可变，改内容须递增版本 | TB-A48 引 plan §2.5.13/§2.5.14（docs/reviews/TB-A48-horizon-ruling.md:26） |

**理由**：① 拆成四个版本需各自走 G1–G7、各自积累 n≥20，审批与样本都翻四倍，却不产生新的研究结论；② 若按周期拆实例，同一持仓会出四条重复风险提示并虚增 n，违反 plan.md:903；③ 正常路径下信号 horizon 取实例值（swing），「缺 horizon」只出现在历史或异常结论的防御路径，用 gap 暴露比拆版本更直接（TB-A48 R3/R4）。

**对计数和门槛的影响**
- H-01 的统计行全部落在 `horizon=swing` 分组；缺 horizon 的观测**不进 n、不进胜率**，只计入 gap 计数并展示（与 RC5 的 `sim_fail_horizon_unknown` 对齐）。
- 发布资格的 n 按版本计一份，不按四周期分别要求 n≥20；H-01 的 RC5 失败窗为 20 日（swing 映射）。
- 晋级清单项数不变，仍为 66（docs/reviews/T-A69-qr31-checklist-ruling.md:7）；不新增 M 行，G7 仍是每版本一次。

**谁做什么**
| 角色 | 动作 | 验收 |
|---|---|---|
| 后端 | P2N-08 恢复时：H-01 结论 horizon 必须等于实例值；为空时只记 gap，不回填 | 定点用例：H-01 四周期版本 + 结论无 horizon → 不计失败、不清零、不进 n，gap=`sim_fail_horizon_unknown`；有 horizon 的观测落 swing 分组 |
| 测试 | 把上条加入离线自检 | 篡改「缺 horizon 回填 swing / 取首元素」必须被拒 |
| 研究员 | T-R35 §2.2 第 2 行、§4.2 末段、§5 第 2 条改为「已裁定（T-A74 ②a）」；卡片不改 | `rg -n "待裁定" docs/strategies/T-R35` 只剩第 ① 项相关条目 |
| 架构师 | 无新增文档同步（plan.md:907、api-contract.md:1280 已含 TB-A48） | — |

## 2. ②(b) T-R35「建议值，待裁定」逐项裁定

出处：docs/strategies/T-R35/README.md:143-155（§2.2 三条）与 :257-269（§5 第 2–5 条；第 1 条属第 ①，不裁；第 2 条见本文 §1）。

| # | 项（T-R35 出处） | 原建议值 | 裁定值 | 理由 | 验收标准 | 复核 |
|---|---|---|---|---|---|---|
| B1 | 「统一 20 日复盘窗」与多跟踪期并存（README.md:151；§5-3 README.md:265） | 发布资格用 n≥20 **或** 满 20 交易日；日常报表仍出 T+1/5/20 三列 | **采纳并补充**：「统一 20 日」只指发布资格窗，不改报表；发布资格的 n = 该版本在**映射跟踪期**（intraday_t→T+1、short→T+5、swing/long→T+20）上 `state=complete` 且可成交的观测数；「满 20 个交易日」按交易日历计 `simulating` 天数，日历缺失日不推进（api-contract.md:1277） | plan.md:959 未写 n 用哪一窗；沿用 T-A36/T-A37 映射（plan.md:780）避免另起一套口径 | 报表三列并存；资格判定：n_映射≥20 或 模拟交易日≥20，且 `verified_live` 与管理员批准缺一不可；日历缺日不计天 | **需另一个模型复核**（发布门槛） |
| B2 | H-01 多周期样本如何计入 n（README.md:153） | 按结论 horizon 分桶；缺 horizon 不进胜率 | **采纳并加严**：缺 horizon 的观测**也不进 n**，只计 gap 并展示 | 不进胜率却进 n 会抬高样本量、提前达到 n≥20 | 见本文 §1 后端/测试验收 | **需另一个模型复核**（RC5/降权输入） |
| B3 | G6 warn 是否计入「模拟健康」否决（README.md:155） | 仅审计标记，不自动挡 simulating 内信号 | **采纳**：G6 warn 经 ack 后只留审计，不挡信号、不降权、不改 G6 结果为 pass，不等同 `verified_live` | 代码只要求 warn 被确认（src/backend/app/strategy/reviews.py:467-475）；plan 无「G6 warn→降权」条文（plan.md:786-792） | G6 warn+ack 的版本进入 simulating 后照常出候选信号，weight 只按 plan.md:787-790 计算；审计可见 `ack_warn_gates` | **需另一个模型复核**（门禁语义） |
| B4 | S-01 发布观察：满 20 日 vs T+5 主报表（§5-4，README.md:267） | 未给值，问是否双重展示 | **裁定**：报表三列照出，S-01（`horizons:[short]`，docs/strategies/cards/st_pullback_ma.md:32）以 T+5 列为主口径高亮；发布资格按 B1（n 取 T+5 完成数，或满 20 交易日） | 与 RC5 short→5 一致（api-contract.md:1280），不用 20 日替代 5 日 | S-01 报表 T+5 列标「主口径」；资格计数取 T+5 complete | **需另一个模型复核**（发布门槛） |
| B5 | `simulating→published` 证据链何时实现（§5-5，README.md:269） | 未给值 | **本期不做**：代码继续硬拒（src/backend/app/strategy/reviews.py:476-484）；首个版本满足 B1 资格前不立项，不进 0030 | 用户要求只推必要功能；现无版本接近 n≥20 | 晋级到 published 仍返回 `PROMOTION_GATES_NOT_MET`（src/backend/selfchecks/test_tb83_promotions.py 现有用例保持通过） | 否（不改阈值） |

**T-R35 附带问题（研究员下轮修，不阻塞）**
1. README.md:171-181 健康度表漏了 `observing→published` 恢复条件（weight≥0.9 连续 10 个交易日，plan.md:1295）。
2. README.md 表格行之间夹空行（如 :15-27、:63-75、:117-135），Markdown 不会渲染成表；空白规范化提交（d8aa73a、5043cad）引入，应去掉表内空行。
3. metrics_slots.json:67-72 `unified_20d_vs_rc5_window` 的 `pending_ruling` 可按 B1 改为正式口径并注明 T-A74。

## 3. ③ 评审 strat/T-R34=cf81d1e：**有条件通过**

- 范围：单提交，只改 docs/strategies/golden/P2N-09_golden.json（+13/-1）与 check_P2N-09.py（+68/-24），基于 174b69d（已在 8e847d5 内），与 8e847d5 合并无冲突；`git diff --check` 通过；作者 noreply。
- 离线自检：`python3 docs/strategies/golden/check_P2N-09.py` → ready 26/26、blocked 0，篡改拒绝 6+15。另做 8 个畸形输入探针（删 render/chain/source_explanation/llm_call_id/viewer_role 等），全部判 finding，无崩溃。
- T-A72 四点：①C12 补 `usage_page_available=true` 泄露变异（check_P2N-09.py:354-360）已做；②管理员未显示 id 改报 `llm_call_id_missing`（:234-237、:253-256）已做；③auth/cache 前置 assert 改 finding（:214-217、:224-230、:241-247、:260-266）已做；④C14 核对 id_text（:255-256）已做。

**待修（不阻塞合入，研究员下轮）**
1. P2N-09_golden.json:477-488 新增 `mutation_probes` 没有被脚本读取（脚本内变异是硬编码的），属于死数据，日后会与脚本漂移。改为由脚本遍历该字段，或删掉。
2. check_P2N-09.py:287-428 自检本身仍全靠 `assert`：`python3 -O` 下所有校验被跳过，却照样打印 26/26 与 6+15（已实测）。应改为显式 `if … : raise SystemExit` 或计数比对。
3. check_P2N-09.py:236-237、255-256：id_text 与 llm_call_id **不一致**也报 `llm_call_id_missing`，与「未显示」混在一起；建议另设 `llm_call_id_mismatch`。
4. check_P2N-09.py:411 `assert not isinstance(got, BaseException)` 恒真，无检验作用；:420 `t_a71_t_a72_input_mutations: 10` 是写死常量，不是实际计数。C14、C21 的前置条件变异未入自检（只覆盖 C12 角色、C13 标志）。

**合入条件**：可随 strat/T-R33 一并合入 main；上述 4 条下轮修完由架构师复核。
