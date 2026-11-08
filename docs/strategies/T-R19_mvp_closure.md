# T-R19 三键 MVP 收口方案（策略研究员，2026-11-07，**待架构师裁定，未批准实现**）

输入：team/reports/T-B81.md、535f9fc `src/backend/probes/tb81_evidence.py`（只读）、本地 `results/run-20261107-190759-T-B81/analysis.json`、`T-R18_source_matrix.yaml`、feature_spec §7D、plan 574（G2）、955（published 须全部 verified_live）。没有调用麦蕊或 DeepSeek，没有读取凭证。

## 0. 结论边界
- **f.amount**：在 matrix 中登记为样本限定的 verified_live（不是全市场推广）。范围只有 688018、300364 各 25 根，a/(v×100) 有 50/50 落在价界内，其他尺度 0/50；元单位依赖 V1 的 v=手。feature_spec 暂不升级，matrix 证据登记与全局状态源待架构师确认后同步。amount 通过不会解除其他键的门禁。
- matrix 中 `current_status` 已同步：5 个键为 verified_doc（§7D），amount 为 verified_live（样本限定），3 个键为 declared（market_regime 只核实了代码子项，不等于整体）；recommendation 是历史建议。
- 下面三个方案都不是已批准的实现；**G2 不通过**：H-01 卡在 market_regime，W-01 卡在 main_net_20d、market_regime、ind_rs20 和 amount（待裁定）。

## 1. f.main_net_20d（W-01 A1 入场、C2 反证）→ 首选：四字段求和（保留 F21 语义）
- 语义：Σ 近 20 个有效交易日 (zmbtdcje+zmbddcje−zmstdcje−zmsddcje)，即“特大单加大单的主动净买额”。内置 `main_20d_net` 定义未公开：688018 的值 12807880 与四字段和 1499643492 相差 −1486835612，比值约 117.09，不能用换单位解释。**两者不等价，禁止互相替代。**
- 选四字段求和的理由：公式和字段有文档依据；T-B81 证明 20 日窗口完整、单日接口与历史接口一致；每天 1 次请求，不需要额外请求。内置因子语义不明，不选。
- 剩余门禁：单位（原始单位未核实）、特大单和大单的阈值、盘后定稿时间（PIT）。A1 只用符号（>0），单位不影响判断；但阈值和定稿时间影响 PIT，所以状态最多到 verified_doc/simulating，仍是 declared，直到裁定。
- 最少实测（估计）：同一只股在 d 日 15:40 后和 d+1 各取 1 次 transaction，比较是否被覆盖（每只股 2 次 × 样本数 k，k 待定）。阈值只能由官方答复，不用请求。

## 2. f.market_regime（H-01 C1 反证、W-01 V1/I2 否决和失效、applicability）→ 首选：简化为 `f.market_regime_idx`（新键）
- 定义：只用 000300.SH 日线（T-B81 已核实代码和路由，64 根）：收盘 > MA60 且 MA20 > MA60 → uptrend；收盘 < MA60 且 MA20 < MA60 → downtrend；其余 range；2 日防抖。**去掉 F24 宽度条件，所以必须用新键名、spec 版本递增**，原 `f.market_regime` 保持 declared，不能沿用原状态。
- 影响：卡片需要升版本（H-01 C1、W-01 V1/I2/applicability 改引用新键），并给出前后差异：不看宽度后，“指数涨、宽度弱”的日子会从 range 变为 uptrend（W-01 准入更宽，H-01 反证更多）。失效条件：指数与宽度明显背离（窄幅、权重股行情）。
- 剩余门禁：指数日线复权语义（指数一般不复权，**待核实**）、可见时点、MA60 预热需 ≥60 根（64 根够用，但历史回测需要更长）。不需要新增请求类型，每天 1 次指数日线。
- 不选“等 F24”：F24 需要全市场快照历史回算，请求量大，且 F24 本身没有状态。

## 3. f.ind_rs20（只有 W-01 C1 反证用，weight 0）→ 首选：W-01 MVP 删除 C1（降级）
- 依据：没有能证明身份的申万一级行业指数和中证全指序列，板块名称不能代替指数身份；用成分股自合成需要加权裁定，并且请求量 ≈ 行业成分数 × 21 根，不是最小方案。
- 做法：W-01 version_no 1→2，删除 C1 和 data_needs 中的 f.ind_rs20，记录前后差异：C1 只是反证，weight 0，入场、离场和否决都不变，只减少一条反证展示。影响的假设：“行业弱势时减少追高提示”没有了。失效条件：行业轮动剧烈时，回踩信号的反证不完整，用户须自行判断行业。科学结论（行业强度有价值）**不改**，F27 保留 declared 和来源缺口，以后可恢复。
- 剩余门禁：无新增；f.ind_rs20 本身仍是 gap。

## 4. 需裁定与后端动作
1. 确认把 amount 的样本限定 verified_live 同步到 feature_spec（目前只登记在 matrix）。
2. 批准或否决上述三个首选方案；批准后，研究员改 feature_spec（新增 F25b，版本递增）和两张卡片的版本，后端再接入。
3. 后端：main_net 覆盖测试（估算见 §1）；指数复权确认。在这之前不发起任何新调用。

## 5. 采纳记录（T-R20 落地，plan「T-R19 裁定」①–④，78de694）
- ① amount：feature_spec 全局状态升为 verified_doc（v1.1.13）；T-B81 只算样本级证据；matrix current_status 与 feature_spec 同步。
- ② main_net_20d：采纳四字段派生（F21 正文和 YAML 写明公式与符号），单位和定稿时间待后端覆盖测试，仍为 declared → **W-01 v2 G2 仍阻塞**。
- ③ 新增 F50 `f.market_regime_idx`（000300.SH，adjust none，不含 F24，2 日防抖），verified_doc；F25 不改。
- ④ H-01 v2、W-01 v2：改用 F50；W-01 删除 C1。v1 冻结在 cards/history/ 和 golden/history/。26 例中只有 W01-FX4 的 rule_ids_passed 少了 C1，state 和 action 全部不变；features 只是改了键名，series 一致（对照见 T-R20 报告）。上文 §1–§3 的其余内容是提案时的记录。
