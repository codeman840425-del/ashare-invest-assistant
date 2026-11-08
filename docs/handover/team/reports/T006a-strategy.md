# T006a 报告（策略研究员）
更新时间：2026-11-01 13:16 (America/Denver)；未提交 git（权限外），改动仅 docs/strategies/。

## ① horizon_classifier
- 新建 docs/strategies/horizon_classifier.md：确定性规则（闸门 HG1–HG6；四周期分项满分各 100；score≥60 为适合；平分按 long→swing→short→intraday_t；输出 {suitable, scores, reasons, classifier_version} 与 /horizon-assessments 契约一致；6 个示例用例）。
- 粘贴位置（见文档 §0）：§4 的 rules: 替换 plan.md 第 2277–2278 行；§5 扩充第 2262–2276 行 features:；第 2280 行加说明；第 535 行可选加引用。

## ② T+1 持有方向阈值（validation.md §7.1A，v0.3）
- 推荐固定阈值：T+1 开盘到收盘的 |超额| ≤ 1.0%。按波动随持有期平方根增长折算：2%/√5≈0.89%，5%/√20≈1.12%，取整 1.0%；下限 0.5% 覆盖示例往返成本约 0.30%。
- 备选：thr=clamp(k·σ·φ, 下限, 2%)，需新增 f.excess_ret_std_60d，k 待校准。
- 剔除停牌、一字跌停、强制持有；只展示，不计入健康度；n≥30 后再校准。需编排者拍板后写入 C(7)。

## ③ ST 涨跌幅 5%→10%：属实（docs/strategies/market_rules_check.md）
- 上交所 上证发〔2026〕41号、深交所 深证上〔2026〕551号，2026-04-24 发布，2026-07-06 生效。沪深主板 ST/*ST 5%→10%；创业板/科创板 20% 不变；北交所 30% 不变。
- 出处：
  - <url>
  - <url>
  - <url>
  - <url>
  - <url>
  - 其余见 market_rules_check.md
- _template.md 的 §7.2、§17 已同步，并注明回看历史时按当时有效的那一段规则计算。

## ④ 对齐 api-contract v0.2 / plan §2.5.14 H / plan §9
- _template.md v0.3：risk_level、refs[]、ref、not_triggered、passed/evidence_ids、嵌套 stops、整数 score、样本量阈值 5/30、新 DSL 函数（max2、for p.x days）；附录 A 示例卡重写，6 个 fixtures（FX1–FX6）经求值器核对全部一致；附录 B 第 3、5、8–14 项标为已解决，新增第 15–20 项。
- catalog.md v0.3 同步 plan §9 C(1)–C(8)；validation.md 对齐。
- docs/strategies 内所有 yaml 块可解析，strategy-card 真卡块数为 0。

## 需要谁做什么
架构师：
1. market_rules.yaml：2026-07-06 之前的历史段过于简化（未体现创业板/科创板历史涨跌幅）；缺 ST 单日累计买入不超过 50 万股（M5）和只能限价申报（M6）；M7 公式与规则对不上；可关闭 plan 问题 36 与 §2.13 的“待核实”。
2. 契约与 plan 冲突：
   - oos_result 在契约里是 string，plan 第 881 行是对象；
   - 卡片级 refs 与列表项 ref 同名不同义；
   - RuleRef.passed 和 rule_ids_passed 在 veto/counter 规则上的含义未定义；
   - 一字涨停夹具该判 G-01 否决还是 LIMIT_LOCKED 未定；
   - T-01 入场要用 ctx.now_hhmm，与“ctx 只能用在 hold/weakening/exit 规则”冲突。
3. 分类器：reasons 缺周期和正反方向字段；scores 不允许 null；profile 字段与 plan 第 1170 行冲突；特征键需统一前缀并登记新键；rules 块结构待确认；按 §0 把规则合入 §6.1。
4. 参考价口径：§2.8 第 953 行与 §2.8.1 第 960 行不一致。

编排者：
- 拍板 T+1 阈值（建议 1.0%）。
- 问题 19：分红是否计入摊薄成本。

后端：ctx.highest_close_since_entry、max2、for p.x days 依赖 T-B42 上线。
