# T-R16 引擎缺口表 v1（16 张知识卡）

> 16 张知识卡**全部不可导入**（83a66cd）。“建议优先级”只是研究员的建议，统一排在 MVP 之后，不构成裁定。“拟议”表示该字段、函数或语义在契约中还不存在，不代表现有能力。
> 类别：**QFQ** `_qfq` 派生（已裁定，尚未实现，和新特征提议分开列）；**ENG** 引擎能力；**RUL** 规则语义或口径（需要架构师裁定）；**DAT** 数据验证（来源、覆盖、延迟、PIT 实测）；**FEA** 新特征提议（未注册）。
> 编号 FEA-6 空缺不用（本轮起草时撤回）。另外，16 张卡还有一项共同的不可导入原因：统一裁定本轮不可导入、不写 golden（不是缺口，不编号）。

| ID | 类别 | 需求（输入 / 时点 / 单位） | 影响卡 | 当前证据 / 未决 | 建议优先级（MVP 后） |
|---|---|---|---|---|---|
| QFQ-1 | QFQ | `plan.stop_loss_qfq`：入场时由结构低点（qfq@as_of）派生，单位元 | S-01, S-02 | 83a66cd 已裁定，未实现 | P1 |
| QFQ-2 | QFQ | `plan.breakout_level_qfq`：入场时由突破位或断板日高点（qfq@as_of）派生 | W-02, S-04 | 83a66cd 已裁定，未实现 | P1 |
| ENG-1 | ENG | 做T两腿配对：同一笔 T 的 sell/buy 腿配对、回补、日终了结；可卖底仓只计 T−1 日及以前 | T-01, T-02, T-03, T-04 | `t_leg` 已有，配对语义缺失；**两腿未配对时不可执行** | P1 |
| ENG-2 | ENG | 入场条件中引用 ctx（`ctx.sellable_qty`；`ctx.now_hhmm` 已在 plan 列出） | T-01, T-02, T-03, T-04 | 目前 ctx 只用于 hold/exit 角色 | P2 |
| ENG-3 | ENG | 组合层：月度调度（`monthly_first_trading_day`）、top-N、行业或组合上限（`screen.per_group_cap`） | L-01, W-04, L-02, L-03, L-04 | plan 中 L-01 缺口已列出，未实现 | P2 |
| ENG-4 | ENG | 盘中实时求值（C(5) 条件满足后） | T-01, T-02, T-03, T-04 | 延迟只有小样本实测；之前只能 post_close_stats | P3 |
| ENG-5 | ENG | 分组截面函数 `rank_pct_in(x, group_key)` | S-01, L-01, W-04, L-04 | plan 已列为新增函数，实现状态待确认 | P2 |
| ENG-6 | ENG | 事件时间锚点：公告后交易日数（拟议 `days_since_ann`），按可见时点计 | W-05 | 不存在 | P2 |
| RUL-1 | RUL | DSL null 放行语义（银行和保险的 `f.debt_ratio_pit` 为 null） | L-01, L-02, L-03 | 待定 | P2 |
| RUL-2 | RUL | 时刻类参数类型（hh:mm） | T-01, T-02, T-03, T-04 | 待定，建议用 enum | P3 |
| RUL-3 | RUL | 按板块换算的近涨停阈值（建议由 `f.limit_up_price` 推导比值） | W-02, S-04 | 拟议 | P3 |
| RUL-4 | RUL | 盘中 `ref`、`for N bars` 的粒度（1 分钟 bar 还是交易日），以及跨日 `ref` 在盘中的取值 | T-02, T-03, T-04 | 待定 | P2 |
| RUL-5 | RUL | 盘中最新价（none）与 qfq@as_of 序列的可比性（当日价格在 qfq@as_of 下不复权） | T-02, T-04 | 待定，需要架构师确认 | P2 |
| RUL-6 | RUL | 参数化时间修饰 `for p.x days` | S-03, W-03 | plan W-01 缺口③ | P2 |
| RUL-7 | RUL | S-03 key：`st_limitup_relay` 与 plan 中 `st_strong_momo` 是否统一 | S-03 | 待定 | P3 |
| DAT-1 | DAT | 1 分钟历史覆盖；`f.vwap_*`、`f.intraday_sigma` 的单位，待 T003 | T-01, T-02, T-03, T-04 | 未核实 | P1 |
| DAT-2 | DAT | PIT 切换门禁（§7A S1/S2：可见时点、截面覆盖率） | L-01, W-05, L-02, L-03 | declared，未实测 | P1 |
| DAT-3 | DAT | `f.sw_l1`、`f.ind_rs20` 的来源，待 T003 | S-01, L-01, W-04, L-04 | 未实测 | P2 |
| DAT-4 | DAT | `f.main_net_20d` 的来源与口径 | W-03 | 未实测 | P3 |
| DAT-5 | DAT | 涨停股池（情绪周期）来源 | S-03 | plan G-02 提及，未实测 | P3 |
| DAT-6 | DAT | 开盘快照（09:25–09:30）延迟实测 | T-03 | 未实测 | P3 |
| FEA-1 | FEA | `f.open_qfq`（日，T 日 09:25 后可得，元，qfq@as_of） | T-03 | 未注册，拟议 | P2 |
| FEA-2 | FEA | 布林带位置 %b（日，比值） | T-04 | 未注册，拟议（可用 ma 和 std 组合替代） | P3 |
| FEA-3 | FEA | 股息率 TTM（PIT，pct，分红公告日可见） | L-03 | 未注册，拟议 | P2 |
| FEA-4 | FEA | 封单额、开板次数（日，CNY / count，T 盘后） | S-03 | 未注册，拟议，来源未知 | P3 |
| FEA-5 | FEA | `f.debt_ratio_pit_ind_pct`（0–1） | L-01 | 未注册，拟议；L-01 已不使用 | P3 |
| FEA-7 | FEA | 个股相对所属行业强度（日，pct，qfq） | W-04 | 未注册，拟议 | P2 |

## 反向矩阵（卡 → 缺口；由同一份数据生成，与上表双向一致）
| 卡 | 缺口 ID |
|---|---|
| T-01 | ENG-1, ENG-2, ENG-4, RUL-2, DAT-1 |
| S-01 | QFQ-1, DAT-3, ENG-5 |
| W-02 | QFQ-2, RUL-3 |
| L-01 | DAT-2, ENG-3, RUL-1, DAT-3, ENG-5, FEA-5 |
| T-02 | ENG-1, ENG-2, ENG-4, RUL-2, RUL-4, DAT-1, RUL-5 |
| T-03 | ENG-1, ENG-2, ENG-4, RUL-2, RUL-4, FEA-1, DAT-1, DAT-6 |
| T-04 | ENG-1, ENG-2, ENG-4, RUL-2, RUL-4, FEA-2, DAT-1, RUL-5 |
| S-02 | QFQ-1 |
| S-03 | FEA-4, DAT-5, RUL-6, RUL-7 |
| S-04 | QFQ-2, RUL-3 |
| W-03 | DAT-4, RUL-6 |
| W-04 | DAT-3, FEA-7, ENG-5, ENG-3 |
| W-05 | DAT-2, ENG-6 |
| L-02 | DAT-2, ENG-3, RUL-1 |
| L-03 | FEA-3, DAT-2, ENG-3, RUL-1 |
| L-04 | ENG-3, ENG-5, DAT-3 |
