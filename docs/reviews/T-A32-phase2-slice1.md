# T-A32 第一切片评审：日报 / 风控 / 跟踪（Phase 2）

- 评审时间：2026-11-08（北京时间，UTC+8）；行号以当前 HEAD（96a4b68）为准，评审涉及文件与 HEAD 无工作区差异。
- 评审对象：后端 01f81245、273be2d0（P2N-02）、a5fc3a92、2f516b55（P2N-03）、b1715678（P2N-04）；前端 e25894b、59261c1、a94e234、d215296、d98ebec、148fc8e（P2N-05a–e）。
- 对照依据：docs/plan-phase2-next.md；docs/api-contract.md §7.7B（T-A29 条件判定口径）、§7.11.1–7.11.3；裁定 8d4b507（T-A25）、1364458（T-A26）、825b682（T-A27）、6df3148（T-A29）。8ab27c2（T-A28，§7.11.4）对应的 P2N-06 尚未提交，本切片不涉及。
- 方法：只读 diff 及直接上下文；定点检查仅 `ruff check`（risk/、tracking/、reports/dimensions.py、api/v1/risk_controls.py，通过）；未跑全量测试或 coverage，未调用任何外部服务。

## 总结论：有条件通过

没有阻断项。本人隔离、缺数据不放行、参数校验和跟踪数值口径都符合契约。有 3 条"重要"需改，都是后端问题：其中两条是 T-A29 裁定（6df3148，晚于 b1715678）后日报还没跟进，一条是 RC1 价格触发在生产路径上实际始终判为 unknown。这 3 条改完后定点复审即可，不需要整轮重审。

## 需改清单

| 编号 | 严重级别 | 文件:行号 | 问题 | 依据条款 | 责任角色 | 建议改法 |
|---|---|---|---|---|---|---|
| R1 | 重要 | src/backend/app/reports/service.py:282-283 | 日报顶层 `data_as_of` 固定写 null，`data_status` 固定写 `partial`。按裁定，`data_as_of` 应取各部分非 null 时点中最早的一个；全部为 null 时 `data_status` 应为 `unavailable` | §7.11.1「日报顶层时点与账户金额」第 1 条（T-A29，6df3148） | 后端 | 汇总 `market`、`account` 计价时点、`stocks[].data_as_of` 和 `stocks[].dimensions[].data_as_of` 中的非 null 值，取 min；全部为 null 时 `data_as_of=null`、`data_status=unavailable`；不用 `generated_at` 代替。补一个定点用例，覆盖"多来源取最早"和"全空"两种情况 |
| R2 | 重要 | src/backend/app/reports/service.py:123-126；src/backend/app/reports/models.py:37-38 | `account` 不为 null 时，`total_assets`、`cash` 仍可能为 null：缺现价或缺现金时整体置 null。前端类型（src/frontend/src/api/types.ts:313-314）已按裁定改为非空，所以前后端现在不一致。前端 `fmtNum` 会把 null 显示成"—"，不会崩溃，但违反契约 | §7.11.1 第 2–3 条（T-A29）；口径同 §7.2 `/portfolio`（portfolio.py 文件头 R6 ③） | 后端 | 复用 `/portfolio` 的口径：没有现金记录时 `cash="0.00"`，并加 gap `cash`；没有现价时按成本估算，`data_status=partial`；账户数据整体算不出时才让 `account=null`，并加 gap `{key:"account"}`。模型里这两个字段改为非 Optional。`pnl_day` 保持现在的 null 加 gap |
| R3 | 重要 | src/backend/app/risk/rc1.py:91；src/backend/app/risk/evaluation.py:441；src/backend/app/workers/assembly.py:229 | 只有 `stops_at == at` 时 `ex_rights` 才会是 False，其他情况都是 None。因此：① 只要已有建议，GET `/risk-controls/evaluation` 的 RC1 价格项就始终是 unknown，gap 为 `rc1.stops_basis_unknown`；② worker 只在生成建议的那一刻判 RC1，所以已持仓的 stops 在之后的盘中和收盘后都不会产生 RC1 触发事件。这个处理是保守的，没有放行，但 T-A26 第 2 条的盘中和收盘补判在生产路径上并没有生效。P2N-02 报告已把它列为"未验收" | §7.11.2 T-A26 第 2 条（盘中、收盘补判、除权 gap `stops_ex_rights`） | 后端 | 补一个可信的除权事实来源，例如比对 stops 生成日以来日线的不复权价与 qfq 因子是否变化，或使用已登记的除权除息表：确认未除权时 `ex_rights=False`，确认已除权时为 True（gap `stops_ex_rights`），无来源时保持 None。再补一个对活跃建议持仓的盘中/盘后 RC1 判定作业，复用 `events.record` 幂等写入。在此之前，界面继续显示 unknown（前端已经这样做），不能把它对外宣称为已可用 |
| R4 | 建议 | src/backend/app/risk/evaluation.py:512 | `RiskEvaluation.data_as_of` 取的是各项观测时点中最新的一个。日报（T-A29）和 TerminalRow 的口径都是取较旧的。契约没有规定这一项，但取最新会让用户高估这份评价的新鲜度 | §1.1；§7.11.1 T-A29 取最早的先例；TerminalRow「较旧者」 | 后端（口径由架构师补进契约） | 改为取最早的时点（min），与日报一致；架构师在 §7.11.2 补一句说明 |
| R5 | 建议 | src/backend/app/tracking/service.py:232、383 | 跟踪行一旦不是 `pending` 就不再重算。到期时缺数据的 `unavailable` 结果会随 `done` 状态被冻结，之后数据补齐了也不会再算 | §7.11.3（契约没有规定 unavailable 能否重算，需要裁定） | 后端（先由架构师裁定） | 建议允许 `unavailable` 在到期后 N 个交易日内重算，并新建一份不可变快照，保留旧快照作为证据；没裁定之前维持现状 |
| R6 | 建议 | src/frontend/src/features/plans/PlanForm.tsx:13 | 界面只在文字里写了"非零"，没有在前端拦截 `pct_change=0` 和早于当日的 `date`。服务端会返回 400，以服务端为准，但用户要提交后才看到错误 | §7.7B 条件判定口径第 3、5 条（T-A29） | 前端 | 在表单里预先校验 pct≠0、date ≥ 北京时间当日，并保留服务端 400 的展示 |

## 已核对通过的要点

- **本人隔离**：风控设置读写都只按 `scope=user AND user_id=本人` 过滤（settings.py:67-72、153-161）；评价接口用 `select_account` 查账户，他人账户返回 404，不存在的证券也返回 404（aggregates/service.py:44-47，evaluation.py:146-148）；RC1 查账本前会再确认一次账户归属（rc1.py:97-100）；风控事件列表按 `user_id` 过滤（events.py:152-154）；跟踪接口 `owned()` 遇到他人建议返回 404（tracking/service.py:46-52）；`bind_instances` 同时限定实例和账户都属于本人；`scope=site` 只返回匿名聚合，不含单条结果或证券代码（tracking/api.py:128-135）；六维快照只读本人 `data_snapshots`，不用他人证书的数据补齐（dimensions.py:90-119）。
- **缺数据不放行**：RC5/RC6 固定为 unknown，gap 为 `business_facts_not_connected`；RC3 没有 F25 时为 unknown，不拿 F50 代替；RC2/RC4 缺额度时 `quantity_cap=null`；有 gap 的项不判 ok（evaluation.py:381-385）；unknown 不会清掉已有事件（events.py:59-64）。六维缺数据时 `value=null` 加 gap，`facts=[]` 时为 `unavailable`，不补 0、不判中性；F21/F23 等没有核实来源的字段直接给 gap（dimensions.py:206-209）。前端把 unknown、缺口和中性分开显示，ok 但有 gap 时不显示为通过（RiskControlsPage.tsx:79-83，DailyDimensions.tsx:28-29）。
- **参数与安全**：参数范围、默认值和 2 位小数限制与 T-A25 的表一致，前后端同源（config_files.py Rc1–Rc5，riskControlParams.ts:12-130）；越界、下限大于上限或精度超限返回 422 `RISK_CONTROL_INVALID_PARAMS`，`fields[]` 指出具体键；重复 control 或未知键返回 400，包括 PUT 带 `default`（`extra=forbid`）；先校验再写入，整次更新原子提交（settings.py:97-149）；GET 返回的 `default` 与 `params` 同形，且不跟随用户覆盖（settings.py:23-47、83）；前端 PUT 只提交 control、enabled、params（phase2Queries.ts:9）。SQL 全部用 SQLAlchemy 绑定参数，advisory lock 也用绑定参数；公告链接只放行没有 userinfo 的 http/https；响应里没有密钥、证书或个人信息字段。
- **RC1 / 时间止损算法（T-A26）**：只用不复权价；`last ≤ stop` 或 `last ≥ tp` 时触发，等号算触发；收盘后用当日 low/high，止损和止盈同时满足时按止损记，时点为 15:00；新鲜度按 `stale_threshold_s` 判断（rc1.py:216-273）。time_stop 起点为第 0 天，按开市日计数，停牌日照常计入，第 N 日 15:00 触发；起点或日历缺失时给 gap（rc1.py:274-323）。触发只产生 warning 级别的 flag，`gated_actions=[]`。
- **跟踪（T-A27）**：路径用入场价加 qfq 收盘价，T+1 只有两个点；回撤 ≤ 0，上行 ≥ 0；缺失的交易日跳过并记 gap，缺入场价或离场价时两项都为 null（engine.py:61-73、292-320）；保留 4 位小数，ROUND_HALF_UP（engine.py:55-58、331-340）；盈亏比只取 buy/add/hold，排除 0 收益，n<5 时为 null，没有亏损样本时为 null 加 gap `no_losing_samples`，有亏损没有盈利时为 0（service.py:171-195）；观测键 (suggestion, version, horizon) 去重，取 created_at 最早、并列时取 id 最小，其他实例列入 evidence（service.py:157-168、327-340；api.py:85-93）；untradable/excluded 必须带 `exclusion_reason`，且不计入有效 n；前端写明"模拟，不代表实际收益"，n<5 显示"样本不足"，显示 2 位小数时按 HALF_UP 取整（TrackingStats.tsx:9-22，TrackingResults.tsx:12）。
- **六维结构**：正好六项，按 §3 顺序；removed 行和旧版日报为 null；证据 id 以证券代码为前缀，且必须能在日报顶层 evidence 中找到，否则校验失败（reports/models.py:83-93、122-133）；快照按内容寻址，同 id 不同 owner 或 hash 时拒绝（dimensions.py:469-488）。
- **前端 T-A29 文案**：条件判定说明与 §7.7B 一致（等号算触发、pct 非零、日期顺延、错过补一次，PlanForm.tsx PlanConditionRules）；日报 `data_as_of=null` 时显示"—（无来源）"，不用生成时刻代替（DailyReportPage.tsx:215）。
