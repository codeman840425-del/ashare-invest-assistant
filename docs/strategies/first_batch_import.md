# 首批策略卡正式导入清单与路径说明（T-R25）

> 版本 v1.0｜任务 T-R25｜2026-11-09 北京时间｜维护：策略研究员
> 依据：`card_promotion_gates.md` v1.1（66 项验收）；plan §2.5.0B/§2.5.13/§2.5.14、T-A14、T-B80 报告；契约 §7.4（promotion-requests）；catalog v0.3.9；feature_spec 7D 状态表。
> 边界：本文只做**研究与预检**。不执行导入（后端 T-B71/T-B25 CLI）、不跑 G1–G6（T-B80 门禁执行器）、不做 G7 决定（T-R25 时写「用户本人」；T-A109 后为编排者在用户本人授权覆盖该卡前提下代批，见 §5 注）。G2 结论以引擎实跑为准（T-R20 ②）。
> 现状基线：库内 cards/versions/instances 全 0（派单）；T-B80 报告：两正式卡 26 golden 通过、仍 `draft`，G2 因四键 `declared` 未过、G7 未执行、正式接线 pending。

---

## 1. 选卡结论（首批 3 张，按导入顺序）

| 序 | 卡 | 文件 | 选择理由（数据可得性 × 规则完整度） | 首批定位 |
|---|---|---|---|---|
| 1 | **H-01** `hold_risk_monitor` v2 | [cards/hold_risk_monitor.md](cards/hold_risk_monitor.md) | ① 数据全部日频：`f.close_qfq/f.high_qfq/f.low_qfq`（verified_doc）、`f.is_suspended/f.limit_down_price/f.limit_locked_down`（verified_doc）、`f.market_regime_idx`（F50 verified_doc）——7 键全部 verified_doc，**无 declared/gap 键**（S-01/W-01 都做不到）；② 规则完整度最高：T-R15 首张正式卡，26 golden 之一，G1 纯离场豁免（T-A03）有裁定链；③ 纯离场组件不产生买入，首批导入风险最小；④ T-A48 已裁定挂载口径（swing），无未决裁定。 | **第一张**：走通全流程的样板 |
| 2 | **W-01** `sw_ma_trend_pullback` v2 | [cards/sw_ma_trend_pullback.md](cards/sw_ma_trend_pullback.md) | ① 与 H-01 同代的第二张正式卡，26 golden 之一，规则/参数/夹具齐全；② 首张**买卖双向**卡（P0 首个买卖卡定位，plan「研究前置」：T-01 只盘后统计、不选为首个买卖卡，W-01 是既定首选）；③ 13 个 data_needs 中 11 键 verified_doc，仅 `f.main_net_20d`（F21，declared）与 `f.np_yoy_latest` 引用的资金/财报链有条件。**G2 缺口已知**：F21 declared → G2 fail 是当前实测状态（T-B80），导入后能否过 G2 取决于后端补源或实测，不在本研究单内解决。 | **第二张**：首个买卖卡 |
| 3 | **S-01** `st_pullback_ma` | [T-R16/S-01_st_pullback_ma.md](T-R16/S-01_st_pullback_ma.md) | ① T-R16 草稿中**数据可得性最好**的一张：全部特征日频且已注册（f.close_qfq/low_qfq/amount/list_days 均 verified_doc；`f.market_regime` declared → 已按 T-R19 ③ 换 `f.market_regime_idx`，见 §3 修卡）；② catalog P0；③ 规则按 DSL 白名单复核（`rank_pct` 在白名单但**求值器未实现**，E1 已改绝对涨幅阈值，见 §3）；④ 短线周期与 H-01/W-01 互补，形成 风险体检 + 波段买卖 + 短线买卖 的最小组合。**golden 已随本单补齐（8 例，见 §3）**，是否放行由 G1–G6 实跑判定。 | **第三张**：草稿转正式卡样板 |

**为什么不选其他 13 张**（摘要，详见 §4 全表）：
- T-01～T-04（做T）：缺做T两腿配对（ENG-1）、1 分钟数据未核实（DAT-1）、盘中延迟未实测（ENG-4）；plan 明确 T-01 只做盘后统计不出候选，**不做首个买卖卡**。
- W-02：规则里 `plan.breakout_level_qfq` 未实现（QFQ-2），C1 近涨停阈值按板块换算未裁定（RUL-3）；golden 未写。
- L-01～L-04、W-03、W-04、W-05、S-02～S-04：依赖 PIT 财务切换门禁（DAT-2）、组合调度（ENG-3）、资金流口径（DAT-4）、行业来源（DAT-3）等未实测/未实现项，数据前提不满足「只有日级回放数据」的首批约束。
- G-01/G-02/N-01：系统组件，不是可晋级卡片（plan §2.5.11A，按 gate/上下文挂载；T-A48 R6：制成正式卡须另走裁定）。

---

## 2. 三张卡的预检结论（对照 66 项验收）

> 完整勾选记录在 §4；本节只列**到「可提交导入」还差什么**。

### 2.1 H-01 v2 —— 可提交导入，0 项待改

| 门槛段 | 结论 |
|---|---|
| P-01～P-06（前置 6 项） | 全过。三块结构、幂等键 `hold_risk_monitor+2`、无真实数据、SYS 字段未填。 |
| F1–F10（必填 8+2 项） | 全过。entry 豁免依据 T-A03（`mount_policy: system_only` + 纯离场角色集）；exit 含 2 条止损类（X1/X2）；`falsified_by` ≥1；`epistemic` 覆盖全部参数。 |
| G1（规则完整） | 预检过（G1-07 豁免链：T-A03 + T-R15 ②）。M-01～M-06 多周期项全过（T-A48 裁定齐）。 |
| G2（数据可得） | **预检过、实跑待验**：7 键全部 verified_doc（feature_spec 7D），无 gap。按 T-R20 ② 以引擎实跑为准。 |
| G3/G4 | DSL 全部白名单函数（`ma`/`atr`/比较/布尔/`for N days`）；参数 6 个全带 min/max/step。X2 的 `ctx.cost_price_qfq` 已在 T-B42 落地。 |
| G5 | `stops` 显式全 null（纯离场不设止损，T-A03 豁免）；涨跌停/停牌/T+1 规则齐全。 |
| G6 | 26 golden 内含 H-01 例（T-B80：两正式卡 26 golden 已通过）。 |
| G7 | 未执行（T-R25 时等用户本人；T-A109 后按 §5 注的代批程序）。 |

**还差**：无研究侧缺口。导入后 G2 实跑结果与 `gates_missing[]` 由后端回填。

### 2.2 W-01 v2 —— 可提交导入，0 项待改（G2 缺口已知、非本单解决）

| 门槛段 | 结论 |
|---|---|
| P/F | 全过（与 H-01 同代正式卡结构）。 |
| G1 | 过：E1–E3 入场全量化、X1–X6 退出（止损类 X2/X6、时间 X3、跟踪 X5）、C2/C3 反证、I1/I2 失效、V1/V2/V4 否决。 |
| G2 | **预检有条件**：13 键中 `f.main_net_20d`（F21）declared（feature_spec 7D 末行：H-01、W-01 的 G2 仍不通过，需实测或补来源）。**这是 T-B80 已知状态，不是本单能修的**——处理路径见 §5「若 G2 fail」。其余 12 键 verified_doc。 |
| G3/G4/G5 | 全部白名单；13 参数全 schema；涨跌停截断/T+1/整手规则齐全。 |
| G6 | 26 golden 内含 W-01 例。 |
| G7 | 未执行。 |

**还差**：研究侧无字段缺口；`f.main_net_20d` 属数据来源问题（T-R19 ② 四字段派生口径已定，实测归 T-B05/后端），**建议导入时接受 G2 warn/fail 如实展示，不阻塞 G7 流程说明**（`ack_warn_gates` 机制：fail 需 rejected/changes_requested 路径，warn 可带确认通过——见 §5）。

### 2.3 S-01 v1 → 需修卡后可提交（本单修）

| 门槛段 | 现状 → 修后 |
|---|---|
| P-01～P-06 | 草稿不是三块结构（P-01 不过）→ **本单重写为正式卡文件** `cards/st_pullback_ma.md`。 |
| F1 | 草稿 key/name/category 合规 → 照搬。 |
| F2 | `[short]` 单周期，无多周期问题。 |
| F3 | why_it_works + 3 条 falsified_by 齐全 → 照搬。 |
| F4 | technical core / sector_market veto → 保留（换 F50 后 veto 维度不变）。 |
| F5 | E1–E4 entry 齐全 → 照搬。 |
| F6 | C1/C2 反证、I1 失效 → 照搬。 |
| F7 | X1 趋势失效、X2 止损（`plan.entry_price_qfq` 口径，当前可用）、X3 时间止损 → **满足「至少一条止损类」且短线 1–5 日定位与 X3=5 一致**。X4（`plan.stop_loss_qfq`，QFQ-1）维持「MVP 后」标注，不进首批规则集。 |
| F8 | 草稿用 `f.market_regime`（declared）→ **改用 `f.market_regime_idx`（F50 verified_doc）**，与 H-01 v2/W-01 v2 同口径（T-R19 ③：新键须出新版本；本卡是首次正式化，无版本问题）。 |
| F9 | epistemic 需覆盖全部参数 → 新增。 |
| F10 | 普通模板 `mount_policy: user`（默认，可显式写）。 |
| G1 | 修后过：E/F/V/C/I/X 角色齐、止损类 ≥1。 |
| G2 | 修后预检过：f.close_qfq/f.low_qfq/f.amount/f.list_days verified_doc + f.market_regime_idx verified_doc。**注意 E1 的 `rank_pct` 是截面函数，白名单内（plan §2.5.14 C），无需分组。** |
| G3 | 全部表达式在白名单（`rank_pct`/`ma`/`pct_change`/`for N days`）；`p.exit_confirm_days` 参数化时间修饰在白名单（H⑤）。 |
| G4 | 9 参数表齐全 → 转 params_schema 映射形式。 |
| G5 | 需补 `stops` 显式声明（X2 止损价公式 + 截断说明）。 |
| G6 | **需补 ≥6 个虚构 golden**（覆盖：满足、不满足、缺数据、维度分歧、涨跌停或停牌、可卖为 0 卖出信号[非做T卡替代场景，plan H⑩]）→ **本单补**。 |
| G7 | 未执行。 |

**S-01 修卡落点**（全部在 docs/strategies/ 内）：新建 `cards/st_pullback_ma.md`（三块结构 + 8 例 golden，E1 改绝对涨幅阈值、大盘键换 F50）；草稿顶部状态改「已正式化，见 cards/st_pullback_ma.md」。

---

## 3. 修订内容明细（本单实际改动）

1. **新建 [cards/st_pullback_ma.md](cards/st_pullback_ma.md)**：S-01 首次正式化。
   - 结构：`yaml strategy-card` / `yaml strategy-spec` / `yaml validation` 三块；正文 narrative 含规则摘要、时点/复权/预热、成本、A 股约束（全部沿用草稿复核结论，不新增规则语义）。
   - 关键替换一：`f.market_regime` → `f.market_regime_idx`（F50，T-R19 ③ 口径；只换键名，规则语义不变——veto 条件仍是「大盘 downtrend」）。
   - 关键替换二（本次研究发现）：**E1 由 `rank_pct(pct_change(f.close_qfq, 20)) >= p.rs_pct` 改为 `pct_change(f.close_qfq, 20) >= p.rs_min`（绝对涨幅阈值，default 0.15）**。原因：`rank_pct` 虽在 DSL 白名单内可解析，但求值器未实现（src/backend/app/features/pipeline.py L109–111 对未定契约函数显式返回 None、注释「never guess」），E1 用它会使一切求值落 `insufficient_data`。截面分位版待 T-B72 定截面输入契约后升 v2。
   - X4（`plan.stop_loss_qfq`）不进首批：`stops.stop_loss` 用 X2 的入场价比例止损（`plan.entry_price_qfq * (1 - p.hard_stop_pct)`），结构止损留待 QFQ-1 实现后升 v2。
   - golden：8 例虚构（FX1 满足、FX2 不满足、FX3 缺数据、FX4 维度分歧、FX5 一字涨停、FX6 停牌、FX7 可卖 0 卖出、FX8 时间止损），数值全部虚构。**期望值已用 Decimal 手算核对**（含持有态下 F1/F2 照常求值、X1 的 `for 2 days` 双日验证、X2 与 X3 互斥性）；导入时 T-B71 fixture 执行器若 diff 以实跑为准回修。
   - 已对照 preflight 校验器（src/backend/app/strategy/cards/preflight.py）逐项自查：必填字段齐、参数 schema 带 type/default/min/max/step/desc、rule id 无重复、role/dimension/eval_time 枚举合法、无 `to_quantify`、`required_features` 全部在 20 键 registry 内、卡片列表 `ref` 角色相容且 expr 一致、fixtures ≥6 且键全在 registry、`LIMIT_LOCKED`/`SUSPENDED` 带 `reason_details.direction`、`entry`+止损齐（非 system_only 分支）、`counter`+`invalidation` 齐、`action_map` 键合法。
2. **[T-R16/S-01_st_pullback_ma.md](T-R16/S-01_st_pullback_ma.md) 顶部状态注记**：标明已正式化为 cards/st_pullback_ma.md（T-R25）并列出三处差异；本文件保留草稿过程记录。
3. 不改 catalog.md（P0 名单与初判措辞 v0.3.9 已就位，正式化不改变研究初判）。

---

## 4. 16 张草稿逐一预检结果（为什么是这 3 张）

| 卡 | 数据可得性（当前只有日级回放、live 未接） | 规则完整度（对照门槛） | 结论 |
|---|---|---|---|
| H-01 | 7 键全 verified_doc，日频 | 正式卡 v2，golden 齐，豁免链全 | ✅ 首批 1 |
| W-01 | 12/13 键 verified_doc，F21 declared（已知） | 正式卡 v2，golden 齐 | ✅ 首批 2 |
| S-01 | 修 F50 后全 verified_doc，日频 | E/F/V/C/I/X 齐，缺 golden（本单补） | ✅ 首批 3（修卡） |
| S-02 | 同 S-01 基础，但 X1b 依赖 QFQ-1；golden 未写 | 止损依赖 `plan.stop_loss_qfq` 的结构位 | ⏸ 第二批（QFQ-1 实现后） |
| S-03 | 封板类因子不可用（GAP 观察）、FEA-4 未注册 | 情绪周期来源未定（DAT-5） | ⏸ 数据前提不满足 |
| S-04 | QFQ-2（断板日高点）未实现 | X 规则依赖突破位派生 | ⏸ QFQ-2 后 |
| T-01 | `f.vwap_intraday` 盘中；plan 限定只做盘后统计 | 两腿配对 ENG-1 缺失 | ⏸ 且不做首个买卖卡（plan） |
| T-02 | 1 分钟未核实（DAT-1）+ ENG-1/2/4 | 同上 | ⏸ |
| T-03 | 竞价只有盘后 + FEA-1 未注册 | 同上 | ⏸ |
| T-04 | FEA-2 未注册（可用 ma+std 替代但需改写）+ DAT-1 | 同上 | ⏸ |
| W-02 | 特征已注册（F31/F32）但 golden 未写 | QFQ-2（突破位）未实现；RUL-3 未裁定 | ⏸ 第二批（QFQ-2 + RUL-3 后） |
| W-03 | `f.main_net_20d` 未实测（DAT-4） | RUL-6 参数化时间修饰待定 | ⏸ |
| W-04 | `f.sw_l1` 来源未实测（DAT-3）+ FEA-7 | ENG-3 组合调度未实现 | ⏸ |
| W-05 | DAT-2 + ENG-6（事件锚点不存在） | 依赖公告事件时间 | ⏸ |
| L-01 | PIT 切换门禁 DAT-2 未过（feature_spec §7C S1） | 组合层 ENG-3 + RUL-1 null 语义 | ⏸ 切换条件过门禁后 |
| L-02/L-03/L-04 | DAT-2 / FEA-3 / ENG-3 | 同 L-01 族 | ⏸ |
| G-01/G-02/N-01 | — | 系统组件，非可晋级卡（plan §2.5.11A） | ➖ 不入选 |

---

## 5. 导入到 G7 的完整路径（谁做什么、用户点什么）

> 页面与接口以当前前端路由/契约为准：管理端门禁页 `/admin/strategy-gates`（routes.tsx 已挂载）；后端 `promotions.py` 四端点已实现（T-B83/T-B83b/T-B87）。**执行前提是后端 T-B80 正式放行（G1–G6 执行器接入 + 正卡接线），本单不改变其 pending 状态。**

| 步 | 谁 | 做什么 | 落点 |
|---|---|---|---|
| 1 | 研究员（本单已完成） | 提交正式卡文档（3 张）+ golden | docs/strategies/cards/ |
| 2 | 后端 | 跑 T-B71 导入 CLI：`python -m app.cli.cards_import --card cards/<卡>.md --catalog ... --market-rules ... --apply`（幂等键 key+version_no；golden mismatch 则拒绝导入）；产出导入报告 | 库中 `strategy_card_versions` + `draft` 状态 `strategy_versions`；cards/versions 从 0 → 3 |
| 3 | 后端（T-B80 放行后） | 门禁执行器跑 G1–G6，产出逐门禁报告（每条规则与卡片原文对应、证据、缺口） | `/admin/promotions` 列表可见 |
| 4 | 管理员（可由运维/后端代操作） | 对每张卡 `POST /strategy-cards/{id}/promotion-requests {version_id}` → 202，触发 G1–G6 后台跑 | review_id 生成 |
| 5 | **用户本人** | 登录 → 打开 **管理后台 → 策略门禁**（`/admin/strategy-gates`）→ 看到待审列表 → 点开某张卡的门禁报告 → 并排核对「卡片原文 vs 规则逐条对应」与 G1–G6 结果 → 点「批准」→ **弹窗要求重新输入本人密码**（T-A18/T-A20：每次决定须密码复核，浏览器会话 + `origin: password_login`，API token/脚本一律 403）→ 提交 | `POST /admin/promotions/{review_id}/decision {decision: approved, ack_warn_gates: [...], password}` |
| 6 | 用户本人（同页） | 批准后如需正式启用，同页点「晋级」，再次密码复核 | `POST /admin/strategies/{id}/versions/{vid}/lifecycle`（draft → simulating） |
| 7 | 系统 | 进入 `simulating`：产生候选信号、模拟跟踪、显示"模拟中"、**不生成计划草案**；只有管理员实例化（T-A14 ④） | 候选/建议/日报链 |

> **T-R47 注（T-A109 后）**：上表第 5、6 步为 T-R25 当时写法（用户本人点批准/晋级），保留为历史。现行条款见 `docs/reviews/T-A109-g7-delegation.md` §2、§6：全站内置/共享模板由策略研究员逐条核对 → 架构师复核 → **编排者**在用户本人授权覆盖该卡前提下，在目标环境以管理员可信交互会话执行 decision（重输密码，comment 引用授权日期、覆盖卡片与原话或 T-A109）并留证，再执行 lifecycle；前提为缺证据项为 0 且 G1–G6 结论齐备（无 fail，warn 均已 ack）。据 T-A109 §1 引用，当前书面授权字面仅覆盖 H-01、S-01（W-01 等其他卡须用户本人新授权或确认长期授权，未决）；每次代批须引用一条覆盖该卡的用户本人授权；用户私有模板仍由用户本人确认；2026-11-09 13:12:55 那次代批不作晋级依据。技术门禁（password_login、CSRF、每次重输密码、拒脚本/API token）不变。

**G7 页面细节（T-R25 时写给用户；现由执行代批的管理员会话适用）**：
- 列表页每行 = 一张卡的一个版本申请；`stale`（版本已更新/内容已变）的旧审核只读，须重新申请。
- G1–G6 有 `fail` 时**不能**点批准（后端 422 `PROMOTION_GATES_NOT_MET`）；有 `warn` 时批准须勾选确认该 warn 门禁（`ack_warn_gates`）。
- W-01 预期路径：F21 declared → G2 大概率 `fail`（如实），此时用户应选 `changes_requested` 并注明「等资金流实测（T-B05）」，**不建议绕过**；若后端补源后 G2 转 `pass/warn`，再走批准。
- H-01/S-01 预期路径：G2 全 verified_doc → 若无其他 fail，用户可直接批准 + 晋级。

---

## 6. 遗留与风险

1. **S-01 golden 期望值未经引擎复核**：导入时若 fixture diff，由后端导入报告指出，研究员回修（不阻塞 H-01/W-01 先行导入）。
2. **W-01 的 F21**：数据来源问题，本研究单不解决；导入顺序上 W-01 排 H-01 之后，若 G2 fail 如实展示，等 T-B05/补源后重新申请（重新申请生成新 review，旧 review 标 stale）。
3. **T-B80 正式放行是全部流程的前置**：G1–G6 执行器与正卡接线 pending 时，步骤 3–7 都走不动；本单只保证「文档侧就绪」。
4. **不冒进声明**：本单未执行导入、未跑门禁、未做 G7；所有「预期 G2 过/不过」均为研究预判，以实跑 `gate_results` 为准。
