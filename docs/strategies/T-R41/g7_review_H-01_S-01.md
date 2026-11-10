# G7 人工核对稿｜H-01 / S-01（代理准备，不构成批准）

> **文首声明（必读）**：本报告由**策略研究员代理**准备，是 G7 程序第 1 步的核对稿（一致 / 不一致 / 缺证据）；代理初核≠批准。**本文件不构成批准、不构成晋级、不构成荐股**。用语一律「候选信号 / 计划条件」。
>
> **现行 G7 程序（T-A109，2026-11-10；`docs/reviews/T-A109-g7-delegation.md` §2，plan.md:1000 2.5.13 G7、:3632 T-B80）**——全站内置/共享模板：
> 1. **策略研究员**逐条核对卡片原文与规则的对应关系，产出本核对稿；
> 2. **架构师**复核核对稿与 G1–G6 结论是否齐备；
> 3. **编排者**在用户本人授权覆盖该卡的前提下，以管理员可信交互会话代批，并在决定批注与审计中留证（引用用户原话或指向 T-A109 与授权日期、日期、授权覆盖的策略卡）。
>
> **代批前提（缺一不可）**：缺证据项为 0（含 §4 步骤 A）；G1–G6 结论齐备（无 `fail`；每个 `warn` 已列入 `ack_warn_gates`）。不放松 G1–G6，不放松「缺证据不得批」。**授权范围**：据 T-A109 §1 引用，当前书面授权（2026-11-09）字面仅覆盖 H-01、S-01；是否长期代办、是否覆盖其他卡未决，由编排者向用户本人确认；**每次代批须引用一条覆盖该卡的用户本人授权**。本研究员未独立核验该授权原话。用户私有模板仍由该用户本人确认。2026-11-09 13:12:55 那次代批**不作晋级依据**（T-A109 §3，见本文 §3）。技术门禁不变（浏览器交互会话 + CSRF、`origin=password_login`、每次重输管理员密码；脚本/API token/未获授权代理不得代填密码或代点批准）。
>
> T-R41 时依据原文（**历史引文**，plan 已由 T-A109 修订；T-A109 后现行条款见上）：
> - plan.md:996（旧）—「G7：由用户本人以管理员身份逐条核对卡片原文与规则的对应关系后批准。代理只准备报告，不代为批准。」
> - plan.md:3628（旧，T-B80）—「G7 只能由用户本人以管理员身份审核并点击，任何代理不得代为批准或伪造。」
>
> 勾选列默认**未勾**（☐，供审核留痕；本稿不替任何人勾选）。代理初核仅填「一致 / 不一致 / 缺证据」，**不是**最终结论。

---

## 0. 使用方式

> T-R47 按 T-A109 改写本节；T-R41 原写法为「用户本人以管理员登录逐行核验后在 decision 页由本人点击批准」（历史）。

1. 架构师逐行复核「卡片原文 ↔ 规格规则 ↔ 证据」与 G1–G6 结论（§4 步骤 A），标注「待架构师复核」的项须在此步确认。
2. 缺证据项为 0 且步骤 A 齐备后，编排者在目标环境以管理员可信交互会话、引用覆盖该卡的用户本人授权，在 `/admin/promotions/{review_id}/decision` 代批并留证（T-A109 §2、§6）。本 Markdown **不能**代替该决定与审计记录。
3. 「用户勾选」列保持 ☐，代理与脚本不勾选。

**对象卡**：
| card_id | 文件 | key | version_no | 说明 |
|---|---|---|---|---|
| H-01 | `docs/strategies/cards/hold_risk_monitor.md` | hold_risk_monitor | 3（T-R49；v1/v2 冻结在 `cards/history/`） | 纯离场系统组件（`mount_policy: system_only`） |
| S-01 | `docs/strategies/cards/st_pullback_ma.md` | st_pullback_ma | 2（T-R55；v1 即 055105a 冻结在 `cards/history/st_pullback_ma.v1.md`；**库内 v1 审核（055105a）作废**） | 短线候选信号卡（正式化自 T-R16 草稿） |

**公共证据（本工作树当前 HEAD，代理本地跑通；非库内 promotion 报告）**：
| 检查 | 命令/路径 | 结果（代理观测） |
|---|---|---|
| 格式+fixtures 虚构标 | `docs/strategies/golden/check_T-R15.py` | PASS（含 H-01 11 fixtures、S-01 10 fixtures；S01-FX9/FX10 为 T-R43 新增 C1/C2 正例） |
| horizon census | `docs/strategies/P2N-R10/check_horizons.py` | PASS identity=45（T-R49 起含 H-01 v2 冻结身份；T-R55 起含 S-01 v1 冻结身份）/ scope 见 R10；T-R42 另增非身份文件 |
| 相关提交 | `fe2afa5`（T-R40 S-01 FX 标虚构）、`4c00ae7`（T-R43 S-01 增 FX9/FX10 与卡头 ③）、`055105a`（T-R25 S-01 正式化，即库内 v1）、`e3daf66`/`b752487`（H-01 v2/v1）、`464edfc`（T-R49 H-01 v3） | 仅文档史；**不是** G7 批准记录 |

---

## 1. H-01｜hold_risk_monitor v3 逐条核对（T-R41 按 v2 起稿；T-R50 全部 20 行按 v3 卡行号重核）

| # | 核对主题 | 卡片原文（文件:行） | 规格/规则（文件:行） | 当前证据 | 代理初核 | 用户勾选 |
|---|---|---|---|---|---|---|
| H1 | 身份 key/version/card_id | hold_risk_monitor.md:31 `key`、:32 `version_no: 3`、:36 `card_id: H-01`（v3） | strategy-spec:94-95 同 key、`version_no: 3` | check_T-R15 key 一致检查；R10 正式身份 record；**T-R50（按 v3 重核）**：卡↔规格自洽（3/3）；本地对 origin/main=e44311a018270d4db2c111ca04015ff3b86c10a8 叠 v3 卡跑生产 `preflight` 无错，card/spec version_no 均 3；R10 当前身份为 `hold_risk_monitor@3`（v1/v2 冻结在 history）。**T-R53（导入侧已落，main = 00538a1760d704eab6c36789ae36a0784a9566b9）**：T-B121=17a7c10 把 `config/engine_policy.yaml` 顶层 `version_no`（:2）与 hold_risk_monitor 组件版本号（:18）改为 3，并重生 `config/strategies/*.yaml`；T-B122=894a882 在 `src/backend/selfchecks/test_tb71_import.py:163` 增离线用例，覆盖 T-A119 ② 的 (a)–(d)：(a) 两张正式卡身份 H-01 v3 / W-01 v2，卡与 spec 版本号一致（:171-178，期望表 :22-25）；(b) 生成快照与 `config/strategies/` 逐字节相同（:180-185）；(c) 政策顶层版本号为 3 且 hold_risk_monitor 组件版本号等于卡版本号（:187-194）；(d) v3 政策摘要不同于 v2 修订（:196-206）。库例（需隔离 PG，本地 skip）里原来写死 2 的断言已由 T-B121=17a7c10 改过：原 :65 现为 :70-73，其中 :72 按库内 strategy key 查一张写死的期望表（hold_risk_monitor 为 3、sw_ma_trend_pullback 为 2），不是从卡读版本，也未含 S-01；原 :238/:244 现为 :292/:298，同样按 key 查表（H-01 为 3、W-01 为 2）（T-R55b 按 bb27e71 核实，T-A122 :15、T-A124 :12 指出漏 :72）。T-R53 亲跑（00538a1 临时只读 worktree，env -i 无库无凭据）：:163 通过；临时把 engine_policy.yaml:18 或 :2 改回 2，:163 均失败，还原后通过。剩余代批前置只剩部署侧，见 §6「H1 前置」行 | 一致（卡↔规格；导入侧 2→3 已落于 main 00538a1，T-B121/T-B122） | ☐ |
| H2 | 多周期 horizons | :35 `[intraday_t, short, swing, long]`（v3 未变） | spec:97 同列表 | check_T-R15 horizons 枚举；R10 `explicit_multi`；**T-R50（按 v3 重核）**：行号不变；v3 F1/F2 的 h∈{1,5,20} 按 RC5 口径 B 映射、缺 horizon 记 gap（:42、:133），与四周期一致，结论不变 | 一致 | ☐ |
| H3 | 纯离场 / 无开仓 | 文首:3、:37 `mount_policy: system_only`；无 entry 列表 | spec:106-113 仅 exit/weakening/counter/invalidation；:114 action_map 无 buy/add | check_T-R15 纯离场分支；文首自称 G1 豁免依据；**T-R50（按 v3 重核）**：v3 删去 why 中「只给出风险方向」，改为风险提示 + 组合风险限额（:40），仍无开仓主张，结论不变 | 一致 | ☐ |
| H4 | 假设 hypothesis | v3：card:39-43（:40 why、:42-43 F1/F2）、:123-126 v3 变更、:128-151 证伪口径、:153-158 gaps；v2 原文见 `cards/history/hold_risk_monitor.v2.md:39-43` | （叙述性；无独立 DSL） | T-R42 `hypothesis_structure_check.py` 结构 PASS（why/falsified_by/counter/invalidation 字段在）；T-R47 语义审核见 §1A：与规则对应、反证/失效、时点均满足，但证伪口径不全（:42「显著」无检验口径、:43「超额」无基准、W2/W3/X1 无证伪条件）→ 仍缺证据，缺什么见 §6；T-R48 出 v3 证伪口径差异稿 `T-R48/H-01_v3_falsification_diff.md`（未落卡，H4 仍按现行 v2 判定）；T-A111 :11确认 H4 仍缺证据并给 v3 最低要求；**T-R49 按 T-A112 落 v3**（`cards/hold_risk_monitor.md` version_no 3），按 v3 复审见 §1B：§1A d/e 缺口按 T-A112 §1.8 方案 B 与 P-1~P-7 消除 → 改「一致」，T-A112 §3 要求的落卡后架构师再复核已由 T-A115 :3 完成（确认一致）；**T-R50（按 v3 重核）**：只更新行号；架构师 T-A115 :3 复核「H4 结论：确认一致」（按 v3 卡 :40、:23、:42-43、:154、:155），T-R50 据此改「架构师复核通过」 | 一致（架构师复核通过，T-A115 :3） | ☐ |
| H5 | 维度 dimensions | card:44-46 technical + sector_market | 规则 dimension 字段 :106-113 | check_T-R15 dimension 枚举；**T-R50（按 v3 重核）**：行号不变（:44-46、:106-113），结论不变 | 一致 | ☐ |
| H6 | 离场 exit X1/X2 | 正文:8；card exit :52-54（X1 :53、X2 :54） | spec:106-107 expr | check_T-R15 ref↔role；fixtures H01-FX3/FX4；**T-R50（按 v3 重核）**：X1/X2 规则与夹具 H01-FX3 :270、FX4 :320 未变；v3 F1 只检验 X2（:42、:140-145），不改离场规则，结论不变 | 一致 | ☐ |
| H7 | 转弱 weakening W1–W3 | 正文:9；card exit 列表 :55-57（W1–W3） | spec:108-110 | W1：H01-FX2/FX6/FX10；W2：FX5；W3：FX9（正例；T-R43 按 T-A83 L-3 由 FX6 更正为 FX9）；**T-R50（按 v3 重核）**：夹具行：FX2 :220、FX5 :375、FX6 :425、FX9 :564、FX10 :614，内容未变；v3 只把 W2/W3 定为组合风险限额、不作可检验主张（:23、:40），规则不变，结论不变 | 一致 | ☐ |
| H8 | 反证 counter C1/C2 | card:47-49；正文:10 | spec:111-112 | fixtures H01-FX9；C1 用 `f.market_regime_idx`；**T-R50（按 v3 重核）**：行号不变（card:47-49、正文:10、spec:111-112；FX9 :564），结论不变 | 一致 | ☐ |
| H9 | 失效 invalidation I1 | card:50-51 | spec:113 | fixtures H01-FX9；**T-R50（按 v3 重核）**：行号不变（card:50-51、spec:113；FX9 :564），结论不变 | 一致 | ☐ |
| H10 | 参数 schema | — | spec:98-104 ma_long/ma_break_days/… | check_T-R15 param 类型/范围；**T-R50（按 v3 重核）**：spec:98-104 不变，结论不变 | 一致 | ☐ |
| H11 | 数据 data_needs | card:58-65 data_needs（含 qfq、limit、suspended、market_regime_idx 等；:66-73 为 epistemic，T-R43 更正范围） | 规则 required_features 引用同键 | check_T-R15 data_needs∈feature_spec catalog；**T-R50（按 v3 重核）**：行号不变（:58-65；:66-73 epistemic）。v3 证伪口径 :143 用 `f.amount` 算冲击档，属研究侧模拟跟踪，不是规则输入，所以不进 data_needs；结论不变 | 一致 | ☐ |
| H12 | 标的 universe | card:74-77 持仓范围；北交所不含见 a_share | screen:null :118 | 文档层一致；**运行时挂载策略未在本报告核实**；须后端执行链用例，文档不能补（§6）；**T-R50（按 v3 重核）**：行号不变（:74-77、spec:118），结论不变。线索：origin/main 已有 `src/backend/selfchecks/test_tb113_h12_s12_screen.py:20`（`screen_membership` 合成 universe），未用本卡 universe、未经执行链；是否足以补证由架构师定；**T-R53（T-A118 ①③⑥，main 00538a1760d704eab6c36789ae36a0784a9566b9；行号取自 00538a1）**：生产用例 `tests/backend/unit/test_g7_board_in_universe_prod_t_t66.py`：:57 断言 `signals/service.py` 绑定的就是生产 `universe_norm.board_in_universe`；:62/:73/:84/:95 直调生产函数（北交所排除、主板别名、空板、未知键 fail-closed）；:106 篡改自证；:372/:383 经 `write_candidate` 走 `service.py:355` 门闩（需 o61 临时库）。T-T63 已改调生产函数（T-T67），复刻函数已删：:121 preflight 读本卡 pool=持仓、system_only、bse 为 false（卡 :76）；:131 生产 `creation.create` → 422 `STRATEGY_SYSTEM_ONLY`；:171/:177/:188 北交所排除、主板可入、篡改自证；持仓/未持有接 `test_tb113_l1_l10_runner_h12_h17_t_t46.py:240`（生产 `screen_membership`）。T-R53 亲跑：T-T63、T-T66、T-T46、tb71_import 四文件离线 34 passed / 3 skipped（均为需库夹具）/ 0 xfail / 0 XPASS，另 :372/:383 两条库例因无 o61 库 ERROR（未跑）。篡改：universe_norm.py:42 全放行 → 9 failed（T-T63 :171/:177/:188/:202，T-T66 :62/:73/:84/:95/:106）；service.py:54 后把 board_in_universe 重绑为恒真 → T-T66 :57、:106 失败；creation.py:181 不抛 422 → T-T63 :131 失败；screen.py:44 关 system_only → T-T46 :240 失败；screen.py:42 未持有也放行 → T-T46 :240 等 3 例失败；均已还原，被测生产 blob 与 00538a1 相同。T-R53 时离线可跑的用例抓不到 `service.py:355` 调用点直接短路，H12 暂记缺证据；**T-R53b（库例证据，team 报告 T-R53-dbproof，基 main 00538a1，o61 临时库）**：`test_g7_board_in_universe_prod_t_t66.py:372` `test_write_candidate_persist_excludes_bse_via_service_355`（需库；:383 为同链主板放行例）。缺省与显式两种 PG* 各跑一轮：未改动时 :372/:383 2 passed、全文件 12 passed；把 `service.py:355` 板块判定短路后只有 :372 失败（北交所标的被写入候选）、:383 与 10 条离线例仍过；还原后 service.py 与 00538a1 逐字节一致（本角色核对 sha256 相同），回到全过；麦蕊 0。**库例由合并门禁在 o61 亲跑，非本角色亲跑**；本角色离线核对了用例名与行号（:372、:383）及篡改点确为 service.py:355。**残留**：:355 调用点的自证需 o61 库，离线不覆盖 | 一致（T-A118 ③；main 00538a1，T-T66 :57/:62/:106/:372（需库）、T-T63 :121/:131/:171/:188、T-T46 :240；:372 由合并门禁 o61 亲跑，见 T-R53-dbproof；残留：需 o61 库，离线不覆盖） | ☐ |
| H13 | A 股约束 | card:89；正文:17 T+1/涨跌停/零股 | fixtures FX4/FX6/FX7/FX10 | check_T-R15 reason_codes/lot_rule；**T-R50（按 v3 重核）**：行号不变（:89、正文:17）；夹具 FX4 :320、FX6 :425、FX7 :476、FX10 :614，结论不变 | 一致 | ☐ |
| H14 | 成本滑点 | card:82-88；正文:20 离场不因成本放弃卖出 | validation 成本叙述；plan:1614 | T-R42 `cost_replay.py`+`cost_replay_cases.json` PASS（7【虚构】例：买卖/最低佣金/涨跌停锁/T+1/离场不因成本放弃；佣金费率卡上未钉 → 缺口已标）；T-A111 注：plan 成本行号已漂移，现 plan.md:1618；**T-R50（按 v3 重核）**：卡面依据（正文:20、costs :82-88）在 v3 未变，T-A111 :4 复核依据仍成立；`cost_replay.py` 对 v3 PASS。v3 新增 :143 效应门槛 δ 引用同一组成本项、佣金费率未钉记 gaps G4（:157），这部分不在 T-A111 复核范围 | 一致（架构师复核通过，T-A111 :4） | ☐ |
| H15 | 验证/fixtures | validation 块 :160 起，fixtures :173 起（T-R51 按 T-A116 ① 由 :172 更正），H01-FX1..11 在 :174/:220/:270/:320/:375/:425/:476/:529/:564/:614/:668，desc 均 `【虚构】` | expect state/action | check_T-R15 PASS（11 fixtures）；**T-R50（按 v3 重核）**：check_T-R15 对 v3 PASS；本地对 e44311a 叠 v3 卡，生产 `preflight` 读出 11 例、全部【虚构】，`selfchecks/test_tb71_formal.py::test_all_golden_independently` 26 例全过（H-01 11 + W-01 15）；夹具与期望值与 v2 相同（gen_T-R15 重跑无变化），结论不变 | 一致 | ☐ |
| H16 | 合规/禁用词文案 | 卡内无收益承诺句（代理目视） | G7 decision 另有 compliance_lint（契约 api-contract.md:953） | 服务端：`src/backend/app/strategy/reviews.py:317-324` COMPLIANCE_TERMS+`lint()`（NFKC 后匹配，命中 COMPLIANCE_LINT_FAILED :326），`decide()` :351 lint(comment)、:353 approved 时 lint(card_version.fields)（fields 含 narrative，`cards/persistence.py:110`）；拒绝用例 `src/backend/selfchecks/test_tb83b_reauth.py:246`（仅覆盖 comment 路径）。本地：T-R42 `compliance_lint_local.py` 全卡扫描 PASS（同词表；T-R43 起 `--mutate` 为真实植入，exit 1 且原因含卡与命中词）。词表仅 6 词（plan §8.1），card-fields 路径无专门服务端用例；T-A111 注：词表现 plan.md:3366（稿引 :3362 漂移），`decide()` approved lint 在 reviews.py:352-353；**T-R50（按 v3 重核）**：v3 卡面文本已变（:1、:23、:40、:42-43、新增 :123-158）。本地对 e44311a 叠 v3 卡，调生产 `reviews.lint`（:320）检查全文与 preflight 三块，均未命中，植入「稳赚」会报错；`compliance_lint_local.py` 对 v3 PASS。T-A111 :5 复核的是 v2 卡面；**T-R52：架构师 T-A116 :4「H16 确认一致」**（临时 wt 亲跑生产 lint 扫 v3 全文与三块无命中、植入「稳赚」报 COMPLIANCE_LINT_FAILED） | 一致（架构师对 v3 复核通过，T-A116 ② :4） | ☐ |
| H17 | **horizon 多值风险** | horizons 四周期 :35 | 实例/跟踪若缺 horizon → gap（T-R35 README:89/97；T-A74 B2） | 后端定点用例 `test_tb113_h17_missing_horizon_is_gap_not_counted`（`tests/backend/unit/test_tb113_l1_l10_runner_h12_h17_t_t46.py:327-368`，分支 test/T-T46 = 28c3e7da5525e377280a62b609ed1ad7d419d2cc，T-R44 时尚未合入主线；T-R46 复核：已含于 origin/main = a7ce36285f7abd5fdf9ed5053a3bb51fba43a4b1）：H-01 四周期、`version_horizon=None`，一条已知 short 失败 + 一条 horizon=None 失败（horizon_days 同为 5）→ 断言 gaps 含 `sim_fail_horizon_unknown` 且 `metric.value == 1`，即缺 horizon 不按 5 日计入。被测 `src/backend/app/feedback/core.py:60-133` `simulated_failures`（:103-108 缺 horizon 记 gap 并跳过）；该文件在 be/T-B113 = 52d3bee3071fd0532123036f857aa66ad79569f4、c4e0e74 与本分支基线内容相同。T-R44 在临时只读 worktree 不连库亲跑通过，另做两处临时篡改（缺 horizon 默认 short；记 gap 后仍计入）均使该用例失败，已还原。**范围**：只覆盖 RC5 sim_fail 路径；发布资格 n/胜率按映射周期统计尚未实现（T-R35 B5 本期不做），实现时需另补用例。**T-R48 核实提交关系**：用例所在 28c3e7d（T-T46，2026-11-09 16:48 America/Denver）的父提交即 52d3bee3071fd0532123036f857aa66ad79569f4（T-B113「fix(ingest/signals): T-B113 L-1′/L-10/runner tick + H12/S12/H17 自测」，已含于 origin/main），52d3bee 新增同名后端自测 `src/backend/selfchecks/test_tb113_h17_horizon_gap.py`；被测 `feedback/core.py` 未被 52d3bee 修改，其 :103-108 逻辑最后改于 8219665（P2N-08 slice1，已含于 origin/main）。T-B112=810f89a 为 ingest L-6/7/8，不是 H17 证据（T-A111 :6）。T-A111 裁定发布资格 n/胜率未实现不构成本关缺证；**T-R50（按 v3 重核）**：卡面依据 :35 未变；用例为合成数据、不读本卡，v3 叠加后 `test_tb113_h17_missing_horizon_is_gap_not_counted` 与 `selfchecks/test_tb113_h17_horizon_gap.py` 均过；v3 F1 :133 同样「缺 horizon 记 gap」，一致。T-A111 :6 复核依据未变 | 一致（架构师复核通过，T-A111 :6；范围仅 RC5） | ☐ |
| H18 | null/gap / insufficient_data | 正文:16 预热不足 `passed=null`；FX8 limit null | fixtures H01-FX8 | 后端正式用例 `test_h18_h01_fx8_null_propagates_to_insufficient_data`（`tests/backend/unit/test_h18_null_propagation_h01_t_t48.py:69-95`，test/T-T48 = bec16804ec221af2431fc4a9acfcbacd731699ec；**已含于 origin/main = a7ce36285f7abd5fdf9ed5053a3bb51fba43a4b1**，本地 main 分支 d32a3f6 未更新）：读本卡 validation 块 H01-FX8【虚构】夹具（:30-45 经 preflight 解析本文件；:74-76 断言 limit 价 null、close 序列 3 根 <62），经 `_run`（:48-66）以夹具 features/series/holding/ctx 调生产 `src/backend/app/strategy/cards/fixtures.py:48` `calculate`（:79-83 `Interpreter(...).evaluate`；:84-101 null 记 essential_unknown；:119-120 system_only 持仓→`insufficient_data`；:157-160 limit null 不记 LIMIT_LOCKED）→ `dsl.py:243-254` `Interpreter.evaluate`（:247 null→None 不转 bool；:190 预热不足取 None；:230-231 比较含 None→None；:209-210/:253-254 窗口/布尔传播 None）；断言 state=insufficient_data、action=hold、rule_ids_passed=[]、无 passed=True、至少一条 passed=None、无 LIMIT_LOCKED，并与夹具 expect 一致（:81-95）。实测规则轨迹 X2/W1/C2/I1=None、W2/W3/C1=False。fixtures.py/dsl.py/preflight.py、本卡、feature_spec.md、config/market_rules.yaml 在 bec1680、origin/main 与本分支基线 blob 相同。T-R46 在临时只读 worktree（bec1680）以 `env -i` 不连库、无凭据亲跑 2 passed；临时篡改 dsl.py:190 预热不足取 0、:231 比较含 null 返回 False、fixtures.py:119 去掉 insufficient_data 分支，三处均使该用例 FAIL（rule_ids_passed=['C2','I1'] 或 state=hold_ok），还原后 PASS，worktree 已删。**缺口**：该链未经 `prepare()`（`features/pipeline.py:125`，实盘取数预处理路径未覆盖；生产入口 `features/evaluation.py:133` prepare→:143 RuleEvaluator→calculate）；用例未逐条钉 X2 等每条规则 passed=None，单独把 :247（非窗口）或 :253（窗口）null 改 False 时因其余规则仍为 null 而结果不变、用例仍 PASS，两者同改才 FAIL。T-R42 `null_propagation_replay.py` 仍**不构成 H18 证据**（不读夹具行情，T-A83 B-1）。**T-A111 后更新**：T-T49=bfa2bbe07b196278d07799965d1ecb0f63dbc271（已含于 origin/main）已补逐条 `passed is None` 断言（同文件 :85）与 null→False/null→0 篡改自证用例（:107、:127），上文「未逐条钉 X2 等」缺口已由其关闭；正式断言现位于 :75-104（上文 :69-95 为 T-T48 时行号）。架构师裁定：`pipeline.py:125` prepare 保留 None、不把 null 填 0，**本关不要求再补 prepare() 路径**；残留：实盘取数无端到端用例；**T-R50（按 v3 重核）**：用例按文件读本卡（CARD_PATH = cards/hold_risk_monitor.md），上文「本卡 blob 与 origin/main 相同」在 v3 下不再成立（e44311a 仍为 v2）。本地对 e44311a（fixtures.py/dsl.py/preflight.py/feature_spec/market_rules 与本分支 blob 相同）叠 v3 卡、`env -i` 不连库跑 test_h18 三条全过；临时篡改 `fixtures.py:119` 去掉 insufficient_data 分支 → 该用例与 golden FX8 均 FAIL，已还原。FX8（:529）与正文:16 内容未变。T-A111 :7 复核的是 v2 卡文件；**T-R52：架构师 T-A116 :4「H18 确认一致」**（临时 wt 不连库亲跑 3 passed，篡改 fixtures.py:119 后 3 failed，还原后 3 passed） | 一致（架构师对 v3 复核通过，T-A116 ② :4） | ☐ |
| H19 | 不可执行原因码 | FX4 :320 T1_NOT_SELLABLE；FX7 :476 LIMIT_LOCKED；FX10 :614 SUSPENDED | expect.reason_codes | check_T-R15 与 api-contract 原因码表交叉；**T-R50（按 v3 重核）**：夹具期望未变，结论不变 | 一致 | ☐ |
| H20 | 选股/入场 | **无**（纯离场，设计如此） | :114 action_map 无 buy | check_T-R15 允许 exitonly；**T-R50（按 v3 重核）**：v3 无 entry、无开仓主张，结论不变 | 一致 | ☐ |

> **v3 重核（T-R50，取代 T-R49 影响说明）**：20 行引用的卡行号均已按 v3 `cards/hold_risk_monitor.md` 校正（v3 :1-121 除 :1、:23、:32、:40、:42-43、:95 外与 v2 相同；新增 :123-158；validation 块 :160 起，夹具 H01-FX1 :174 … FX11 :668）。逐行判断 v3 改动是否改变结论：均未改变，状态无降级。需留意：H1 导入侧已升 v3（main 00538a1：`config/engine_policy.yaml:2`/`:18` 为 3，`selfchecks/test_tb71_import.py:163` 离线 (a)–(d) 通过；T-R53 按 T-A119 ④ 改写，原「仍钉 v2」已过时），剩余为部署后 seed 与只读 SQL 验证（§6）；H16/H18 已由架构师对 v3 复核通过（T-A116 :4，T-R52 同步）；H14/H17 的 T-A111 复核依据在 v3 未变。旧审核（v2）随卡内容变更失效（stale），G1–G6 须对 v3 重跑；2026-11-09 书面授权是否覆盖 v3 待用户本人确认（T-A115 :4）。

**H-01 代理小结**：（T-R50：全部 20 行按 v3 重核，H4 经架构师 T-A115 :3 复核通过；H16/H18 经架构师 T-A116 :4 对 v3 复核通过；仍缺证据仅 H12。）（T-R53：H12 改引 main 00538a1 生产用例，复刻残留解除；T-R53b：service.py:355 库例 :372 由合并门禁在 o61 亲跑通过且篡改自证（team 报告 T-R53-dbproof），H12 改一致，H-01 已无缺证据项；残留：需 o61 库，离线不覆盖。）（T-R49：H4 按 v3 改「一致」。）（T-R48：H14/H16/H17/H18 已由架构师 T-A111 :4–:7 复核通过；H18 T-A111 裁定本关不再要求 prepare() 路径。）H14/H16 代理初核「一致」（成本回放/服务端+本地合规）；H18 经 T-R43 按 T-A83 B-1 改回缺证据后，T-R46 按 T-T48 正式用例（T-A86 裁定）改「一致」（规则求值层 calculate→Interpreter；未经 prepare()）；H17 经 T-R44 按 T-T46 定点用例改「一致」（仅 RC5 路径；28c3e7d、bec1680 现均含于 origin/main a7ce362）；H12 曾缺证据（挂载执行链），T-R53b 按 T-A118 ③ 与 T-R53-dbproof 改一致。（T-R47 时 H4 亦缺证据，见 §1A，已由 v3 消除，§1B。）标「一致」的项仍须架构师复核（T-A109 §5）。**不得**据此视为已过 G7。

---

## 1A. H4 假设语义审核（T-R47，策略研究员；架构师 T-A111 :11 复核：仍缺证据）

对象：`cards/hold_risk_monitor.md`（下称 card）v2 `hypothesis`（card:39-43）与正文:23。**本节行号为 v2**，v2 原文见 `cards/history/hold_risk_monitor.v2.md`（同行号）；v3 复审见 §1B。

| 审核点 | 卡片原文依据 | 结论 |
|---|---|---|
| a 与规则一致 | why_it_works card:40 三个驱动 ↔ 「跌破成本缓冲」X2 card:107（spec 块）、「跌破长期均线」W1 :108、「集中度超限」W2/W3 :109-110；「只给出风险方向，不预测收益」↔ action_map :114 无 buy/add、文首 :3 纯离场；X1 :106 为计划绑定止损（正文:8），未入 why 但不矛盾 | 满足 |
| b 反证/失效条件 | counter C1/C2 card:47-49 ↔ spec:111-112；invalidation I1 card:50-51 ↔ spec:113，即 W1 前提消失（正文:10）；X2/W2/W3 为状态阈值，不再超限即不触发 | 满足 |
| c 只用当时可得数据 | 正文:15「只用 as_of 及以前数据」、qfq@as_of；data_needs card:59-65 均为 T 日入库后/开盘前可得；falsified_by 中「20 个交易日后收益」只用于事后模拟跟踪/研究评估，不作规则输入 | 满足 |
| d 可证伪（口径可操作） | card:42「扣费收益中位数**显著**高于继续持有（n ≥ 30）」：n 与 validation 块 min_n（card:130）一致，但「显著」无检验方法/阈值；card:43「20 日**超额**中位数 ≥ 0」：有阈值，未写超额基准（validation_summary :90 benchmark=继续持有，只对应 exit 对照） | **不满足** |
| e 证伪覆盖面 | falsified_by 只覆盖 exit_signal（:42）与 W1 默认参数 MA60×3（:43）；W2/W3 集中度、X1 计划止损无证伪条件；证伪窗口仅 20 日，horizons :35 含 intraday_t/short（validation horizon_days :128 为 [1,5,20]） | **不满足**（或须架构师裁定集中度/计划止损属定义性风险提示、无需证伪） |

结论：H4 **保持缺证据**。缺：d、e 两项（见 §6）。T-A111 :11 确认仍缺证据，v3 量化差异稿见 `T-R48/H-01_v3_falsification_diff.md`（未落卡）。

---

## 1B. H4 按 v3 复审（T-R49，策略研究员；架构师 T-A115 :3 复核：确认一致）

依据：`docs/reviews/T-A112-h01-v3-rulings.md`（ebdab40）§1、§3。对象：v3 `cards/hold_risk_monitor.md`。

| 审核点 | v3 依据 | 结论 |
|---|---|---|
| a 与规则一致 | why :40 可检验部分「跌破成本缓冲」↔ X2 :107、「跌破长期均线」↔ W1 :108；「单只与行业仓位上限是组合风险限额」↔ W2/W3 :109-110 与 epistemic :72-73 `estimate`；正文 :23 同口径；「只给出风险方向」一句已删，不再统辖集中度（T-A112 §1.8 ①②⑤） | 满足 |
| b 反证/失效 | C1/C2 :47-49、I1 :50-51 不变 | 满足 |
| c 只用当时可得数据 | 证伪口径 :129 只用 verified_doc 键；:134 同一快照比值、窗口 T+h 收盘后关闭；:135 剔除不可成交；不做历史回测 | 满足 |
| d 可量化（T-A111 ①②） | 「显著」：:141-144 单侧精确符号检验、BH q=0.10（P-1）、效应门槛 δ=往返成本中位数 k=1（P-3）、n≥30、不重叠（P-7）；「超额」：:148 相对当日其他持仓等权池、|P_T|<5 记 gap（P-4），:154 沪深300 记 gaps G1；F2 α=0.05 不校正（P-2）；参考价过渡与隔夜非共同项记 gaps G2 :155（P-5） | 满足 |
| e 覆盖面（T-A111 ③） | 集中度已改为风险限额、不作可检验主张（方案 B，P-8），falsified_by 只留 F1（X2）与 F2（W1），对应 why 中仅有的两条可检验机制；X1 不单列（T-A111）；h=1/5/20 覆盖四周期，缺 horizon 记 gap（:133） | 满足 |

结论：H4 改 **一致（T-R49 按 v3）**；T-A115 :3 复核确认一致（T-R50 同步）。P-6 方案 B 下不进卡面（T-A112 §1.6）。

---

## 2. S-01｜st_pullback_ma v2 逐条核对（T-R41 按 v1 起稿；T-R55 按 v2 重核 S1–S20）

> **T-R55（编排者裁定 S-01 升 v2）**：本节 S 行一律指向 v2 卡 `cards/st_pullback_ma.md`（version_no 2，:29/:92）。**库内 v1 审核（055105a）作废**：库内导入的是 055105a 的 v1 内容，其后 fe2afa5、4c00ae7 在同一版本号下改过卡面，库内 v1 的审核、内容哈希与 G1–G6 结论均不能用于 v2；须「S-01 v2 导入 + G1–G6 重跑」（§6 代批前置）。v2 相对 4c00ae7 时的卡只改了标题 :1、卡头 :2（v2 变更记录）与 :29/:92 版本号，其余逐行相同，故下表卡行号均不移；逐行重核见 §2C。

| # | 核对主题 | 卡片原文（文件:行） | 规格/规则（文件:行） | 当前证据 | 代理初核 | 用户勾选 |
|---|---|---|---|---|---|---|
| S1 | 身份 key/version/card_id | st_pullback_ma.md:28-33（:29 version_no 2） | spec:91-92（:92 version_no 2） | check_T-R15；R10 正式身份 `st_pullback_ma@2:current_formal…`、`st_pullback_ma@1:historical_frozen`（T-R55）；导入器离线预检三卡 36 个 golden 全过（T-R55 亲跑，未连库） | 一致（卡↔规格；库内尚为 v1，v2 导入为代批前置，§6） | ☐ |
| S2 | horizon=[short] | card:32；spec:94 | RC5 short→5（inventory rc5_boundary） | R10；T-R35 B4 主口径 T+5 | 一致 | ☐ |
| S3 | 假设 hypothesis | card:35-40 | 叙述性 | T-R42 `hypothesis_structure_check.py` 结构 PASS；T-R47 语义审核见 §2A：可证伪（:38-40 三条均有阈值）、反证/失效、与入场退出规则一致、只用当时可得数据，逐条引用卡片行号；附注 :39「胜率」口径未钉；T-A111 残留非阻断同附注（「样本外」可以 validation tracking_sim 为默认） | 一致（架构师复核通过，T-A111 :10） | ☐ |
| S4 | 维度 | card:41-43 technical + sector_market | 规则 dimension | check_T-R15 | 一致 | ☐ |
| S5 | 入场 E1–E4 | 正文:9；card entry:44-48 | spec rules E1–E4（约:105+） | fixtures S01-FX1；check_T-R15 ref | 一致 | ☐ |
| S6 | 过滤/否决（正文 F1/F2/V1） | 正文:10 | spec 对应 filter/veto 规则行 | FX1/FX4；V1→vetoed | 一致 | ☐ |
| S7 | 反证 C1/C2 | card:49-51 | spec:123-126 counter 规则 | T-R43 新增卡夹具 S01-FX9（C1 命中，单日 −6.48%）、S01-FX10（C2 命中，放量 4 亿>20 日均额×1.5）；`T-R43/s01_fixture_eval.py` 按夹具输入复算 FX1..10 全部 state/action/rule_ids_passed/reason_codes 一致（参考层；T-B71 执行器实跑以导入时为准） | 一致 | ☐ |
| S8 | 失效 I1 | card:52-53 | spec invalidation | check_T-R15 | 一致 | ☐ |
| S9 | 退出 X1–X3 | 正文:12；card exit:54-57 | spec exit + stops:137（硬止损公式、time_stop_days:5） | FX7/FX8 | 一致 | ☐ |
| S10 | 参数 schema | — | spec:95-104 rs_min/touch_pct/… | check_T-R15 | 一致 | ☐ |
| S11 | 数据 data_needs | card:58-66（:67-77 为 epistemic，T-R43 更正范围） | required_features | check_T-R15∈catalog | 一致 | ☐ |
| S12 | 标的 universe | card:78-81 全市场优先持仓/自选；bse:false | screen:null | 文档一致；**选股执行链未跑**；须后端执行链用例，文档不能补（§6）；T-R50：卡面 `universe.pool` 字面与卡头:6 ③ 口径差异记 gaps，见 §2B（T-A114 ② 裁定口径可接受，未称运行侧证据已齐）；**T-R53（T-A118 ②，main 00538a1760d704eab6c36789ae36a0784a9566b9）**：a) 只扫持仓∪自选：`test_g7_h12_s12_s20_exec_t_t63.py:364`（preflight 后官方卡 universe → 生产 `screen_membership`）+ T-T46 :277；b) bse 为 false：T-T63 :202（preflight 读出 + 生产 `board_in_universe`）+ T-T66 :62/:372；c) ST：T-T63 :260（生产 `assess`）；d) 停牌：T-T63 :216（生产 `calculate`，S01-FX6）；e) F2 上市天数：T-T63 :251/:337（生产 calculate/Interpreter）。T-R53 亲跑篡改：screen.py:42 → T-T63 :364、T-T46 :240/:277 失败；preflight.py:99 去掉 universe 归一 → T-T63 :202/:364 失败；universe_norm.py:42 全放行 → T-T63 :202 失败；execution.py:145 ST 不拦 → :260 失败；fixtures.py:162 停牌不记 → :216 失败；dsl.py:70 GtE 恒真 → :251/:337 失败；均已还原。a/c/d/e 已由本角色亲证；b) 运行侧门闩同 H12（service.py:355），**T-R53b（库例证据，team 报告 T-R53-dbproof，基 main 00538a1，o61 临时库）**：`test_g7_board_in_universe_prod_t_t66.py:372` `test_write_candidate_persist_excludes_bse_via_service_355`（需库；:383 为同链主板放行例）。缺省与显式两种 PG* 各跑一轮：未改动时 :372/:383 2 passed、全文件 12 passed；把 `service.py:355` 板块判定短路后只有 :372 失败（北交所标的被写入候选）、:383 与 10 条离线例仍过；还原后 service.py 与 00538a1 逐字节一致（本角色核对 sha256 相同），回到全过；麦蕊 0。**库例由合并门禁在 o61 亲跑，非本角色亲跑**；本角色离线核对了用例名与行号（:372、:383）及篡改点确为 service.py:355。**残留**：b) 的 :355 自证需 o61 库，离线不覆盖 | 一致（T-A118 ②；main 00538a1，T-T63 :202/:216/:251/:260/:337/:364、T-T46 :277、T-T66 :62/:372（需库）；:372 由合并门禁 o61 亲跑，见 T-R53-dbproof；残留：需 o61 库，离线不覆盖） | ☐ |
| S13 | A 股约束 | card:86；正文:19 | S01-FX5 涨停锁 LIMIT_LOCKED、FX6 停牌 SUSPENDED、FX7 T1_NOT_SELLABLE（T-R43 更正：S-01 夹具均 board: main，**无科创板夹具正例**；科创板整手/20% 仅卡:19/:86 文字与 config/market_rules.yaml 承载） | check_T-R15；`T-R43/s01_fixture_eval.py` 复算 FX5–FX7 reason_codes 一致；科创板约束由引擎层承载（T-R44 按 T-A85 L-1 补引）：`config/market_rules.yaml:11` star 涨跌幅 20%、`:19-20` 科创板单笔 ≥200 股且 1 股递增、`:23-24` 零股一次性卖出与科创板零股阈值 200；后端用例 `tests/backend/api_app/test_market_rules_lots_t_t19.py:74-76`（科创板股票/CDR 买入单位 200/201/199 等）、`:96-100`（qty_range star=(200,1)）、`:113-116`（科创板零股卖出），该用例只覆盖整手/零股/单笔上限，20% 仅为配置值 | 一致 | ☐ |
| S14 | 成本滑点 | 正文:21–22（estimate） | validation_summary:87 含 cost_model；plan:1614 | T-R42 `cost_replay.py` CR-S14-* PASS（买入可成交/涨停锁；费用参数同源；佣金费率缺口已标） | 一致（架构师复核通过，T-A111 :8） | ☐ |
| S15 | 验证/fixtures | validation S01-FX1..10，desc 均以 `【虚构】` 开头（FX1..8 T-R40 fe2afa5；FX9/FX10 T-R43 4c00ae7；两处改动随 v2 正式生效，库内 v1 只有 055105a 的 8 个） | expect | check_T-R15 PASS；**改前** d75b0ec/d2e7d51 曾因未标虚构失败 | 一致 | ☐ |
| S16 | 合规文案 | 卡头:5「结论只由规则决定；AI 只做中文解释」 | G7 compliance_lint 服务端 | 服务端 `reviews.py:317-324` lint、`decide()` :351/:353（approved 时 lint card_version.fields，含 narrative）；拒绝用例 `test_tb83b_reauth.py:246`（仅 comment 路径）；本地 `compliance_lint_local.py` 全卡 PASS（同 H16；T-R55 对 v2 含新卡头 :2 重跑 PASS） | 一致（架构师复核通过，T-A111 :9） | ☐ |
| S17 | 与草稿关系 | 卡头:3 由 T-R16 草稿正式化；草稿 `T-R16/S-01_…` 已非「知识卡 vN」身份 | R10：草稿 role=`research_draft_superseded_by_formal_card` | R10 census | 一致 | ☐ |
| S18 | 正式化差异 E1/X4 | 卡头:6 E1 改绝对涨幅；X4 未进 v1 | 规则无 rank_pct / 无 X4 | 文档自述；需编排者向用户本人确认是否接受缺口（产品取舍，不在 2026-11-09 代办字面范围内，T-A109 §5；§6） | 缺证据（产品接受度） | ☐ |
| S19 | 不可执行原因 | FX5 LIMIT_LOCKED；FX6 SUSPENDED；FX7 T1_NOT_SELLABLE | expect.reason_codes | check_T-R15 | 一致 | ☐ |
| S20 | 仓位/选股 screen | screen:null :140；卡头:6 ③ 注明「v1 选股只扫持仓 ∪ 自选」（T-R43） | 无自动筛股 DSL（全市场 DSL 暂缓，T-A83 ④） | 卡面口径已写明；**运行侧**「screen:null 只扫持仓∪自选」用例归后端（与 S12 合并），未见 → 缺证据；文档不能补（§6）；T-R50：口径差异见 §2B gaps；**T-R53（T-A118 ②，main 00538a1760d704eab6c36789ae36a0784a9566b9）**：`test_g7_h12_s12_s20_exec_t_t63.py:364/:407/:414` + T-T46 :277：screen:null 拒全市场字面、只扫持仓∪自选（运行侧 `signals/service.py:325-336` 与 preflight 同用 normalize_universe → screen_membership）。T-R53 亲跑篡改：screen.py:39 任意 pool 放行 → T-T63 :407/:414、T-T46 :277 失败；screen.py:42 未持有也放行 → :364 失败；均已还原 | 一致（T-A118 ②；main 00538a1，T-T63 :364/:407/:414、T-T46 :277） | ☐ |

**S-01 代理小结**（T-R55 按 v2 重核后状态不变，见 §2C）：S14/S16「一致」（T-A111 :8–:9 复核通过）；S7 经 T-R43 补 C1/C2 夹具保持「一致」；S3 经 T-R47 语义审核改「一致」，架构师 T-A111 :10 复核通过（§2A）；S20 经 T-R53 按 T-A118 ② 与 main 00538a1 生产用例改「一致」；S12 经 T-R53b 按 T-A118 ② 与 T-R53-dbproof 改「一致」；**仍缺证据** 仅 S18（E1/X4 产品接受度，须编排者向用户本人确认）。**不得**视为已过 G7。

---

## 2A. S3 假设语义审核（T-R47，策略研究员；架构师 T-A111 :10 复核通过）

对象：`cards/st_pullback_ma.md`（下称 card）v1 `hypothesis`（card:35-40）与正文:24-25。

| 审核点 | 卡片原文依据 | 结论 |
|---|---|---|
| a 与入场规则一致 | why_it_works card:36「短期强势」↔ E1 card:106-107（spec 块）；「均线多头排列」↔ E2 :109-111；「缩量回踩 MA10 不破」↔ E3 :112-114 + E4 :115-116；「趋势容易延续」↔ X1 :129-130 跌破 MA10 确认即退出 | 满足（E1 由截面分位改绝对阈值见卡头:6 ①，属 S18 产品接受度，不影响假设↔规则对应） |
| b 与退出/周期一致 | 证伪窗口 5 日（card:38-39）↔ horizons [short] card:32、spec:94；time_stop 默认 5（spec:101）、stops.time_stop_days 5（:137）；RC5 short→5（S2） | 满足 |
| c 反证/失效条件 | counter C1/C2 card:49-51 ↔ spec:123-126，正文:25「C1/C2 命中，抛压未必出清」直接反证 why「抛压较轻」；invalidation I1 card:52-53 ↔ spec:127-128（MA5<MA10 即 E2 多头排列前提消失）；V1 :121-122 大盘 downtrend 否决对应 pitfalls :83 | 满足 |
| d 可证伪（口径可操作） | card:38 样本外信号后 5 日扣费超额（对所属行业指数）中位数 ≤ 0，基准与 validation_summary :87「所属申万一级行业指数」一致；card:39 n ≥ 30 后 5 日胜率 < 45%；card:40 参数邻域 rs_min ±0.05（= spec:96 一个 step）、shrink_ratio ±0.1（= spec:98 两个 step）内结论符号翻转 | 满足；附注：:39「胜率」未写是否扣费/是否对超额，:38「样本外」区间未钉（MVP 以 validation methods tracking_sim 为准），建议架构师复核时定口径，非阻断 |
| e 只用当时可得数据 | 正文:16「只用 as_of 当日及以前的有效日 K；信号最早 T+1 09:30 执行，模拟入场价 = T+1 开盘价。无未来数据」；data_needs card:59-66 均为 T 日盘后/开盘前/18:00 主数据后可得；证伪所用 5 日后收益只作事后评估标签 | 满足（f.list_days :62 可得时点与盘后批次的排程由后端执行链/G2 承载，不涉及使用未来数据） |

结论：S3 改 **一致**（T-R47）；T-R48 记：架构师 T-A111 :10 复核通过。

---

## 2B. S-01 universe.pool 口径差异（gaps，T-R50 按架构师 T-A114 ②）

| # | 差异 | 依据 | 处理 |
|---|---|---|---|
| SG1 | 卡面 yaml `universe.pool: 全市场（持仓 ∪ 自选优先）`（`cards/st_pullback_ma.md:79`）与卡头:6 ③「v1 选股只扫持仓 ∪ 自选」、`screen: null`（:140）字面不一致 | T-A114 ②：口径**可接受**（v1 `screen:null` 只扫「持仓 ∪ 自选」，全市场选股 DSL 暂缓，T-R43/T-A83 ④）；建议卡面改为「持仓 ∪ 自选」并保留「全市场待升版」，或记 gaps；非用户决定项 | **记 gaps，不改卡**：改卡须新 `version_no`、旧审核 stale、G1–G6 重跑；按编排者 T-R50 指示采用记 gaps。下次 S-01 升版（v2）时把 `universe.pool` 改为「持仓 ∪ 自选」并注明「全市场待升版」。**T-R55b：universe.pool 改动推迟到 v3，待用户决定（编排者裁定）**——v2 只升版、规则不动；改为「持仓 ∪ 自选」属规则变更，以后另开 v3，列入收口时交用户决定的事项；v2 卡 :79 仍为原字面 |
| SG2 | 后端允许池仅 `{持仓, 持仓 ∪ 自选}`；按 T-A114 ②，卡面原字面直传仍得 `universe_pool_not_supported`，改写为允许池后放行（T-T63 该例仍绿） | T-A114 ②（代码不必改） | 运行侧证据仍归 S12/S20（缺证据，§6）；口径可接受 ≠ 运行侧用例已齐，S12/S20 状态不变 |

---

## 2C. S-01 v2 逐行重核（T-R55）

依据：v2 卡与 4c00ae7 时卡逐行比对，仅 :1、:2、:29、:92 不同；下列证据均不依赖库内 v1 审核或 v1 内容哈希。依赖库内状态的只有 §4 步骤 A（G1–G6）与 S-01 v2 导入，二者列为代批前置，不计入 40 项。

| 行 | v2 重核 | 结论 |
|---|---|---|
| S1 | :29/:92 均为 2，key/card_id 未变；R10 身份改 @2 并新增 v1 冻结身份 | 一致 |
| S2、S4–S11、S13、S17、S19 | 所引卡行（:9–:22、:32、:41–:87、:94–:140）与审核时逐行相同；check_T-R15、`s01_fixture_eval.py`、R10 在 v2 上重跑 PASS | 一致（不变） |
| S3、S14、S16 | 架构师 T-A111 :8–:10 复核所据文本（假设 :35-40、成本 :21-22/:87、卡头 :5）在 v2 未改；S16 对新卡头 :2 重跑本地 lint PASS | 一致（复核结论沿用，仅文本未变这一点由本角色核对） |
| S7、S15 | FX9/FX10 与 FX1–8 的「【虚构】」标记随 v2 进入版本内容；夹具值与期望未改 | 一致 |
| S12、S20 | T-T63 读的是仓库现行卡文件，T-R55 在 v2 上离线重跑 T-T63/T-T46 共 32 passed、1 skipped（需库）；T-T66 :372 不读 S-01 卡、与卡版本无关，dbproof 结论沿用；残留同前：需 o61 库，离线不覆盖 | 一致（不变） |
| S18 | 卡头 :6 ①② 原文在 v2 未改，仍待用户本人答复 | 缺证据（不变） |

---

## 3. 「13:12:55 管理员审批」与 G7 的关系（只读证据）

> **历史记录（T-R41 时结论，保留原文不改）**。T-A109 后现行条款见文首与 `docs/reviews/T-A109-g7-delegation.md` §2、§3：据 T-A109 §3，13:12:55 那次代批**不能作为 draft→simulating 的晋级依据**；其环境、库内审核是否 stale、是否已 lifecycle 及处置由编排者执行，本稿不判断。下表「plan 现行条文」一行指 T-R41 当时的 plan 旧文。

| 线索 | 内容摘要 | 来源 | 性质 |
|---|---|---|---|
| 代办授权记录 | 称用户私聊原话授权编排者代办 G7；写「2026-11-09 13:12:55（丹佛）H-01、S-01 以管理员密码登录会话批准，ack_warn_gates=["G6"]」 | 编排者维护的仓库外代办记录（路径不入库，T-R43 按 T-A83 L-6 脱敏） | **编排者维护的记录**；本代理只读打开文字，**未独立核验用户本人授权** |
| T-R35 立场 | 「编排者称已过 G7…由编排者代办，尚未经用户本人在架构师处确认，**当前不视为已批**」；plan:996 列为未关闭项 | `docs/strategies/T-R35/README.md:3-4` | 研究员文档转述 |
| plan 现行条文 | 用户本人逐条核对后批准；代理不代批；T-B80 同旨 | plan.md:996、:3628 | 仓库权威条文（**未因代办文件而修订**） |
| 系统门禁 | `human_admin`：拒 `Authorization` Bearer；要求会话 `origin=="password_login"`，否则 `403 HUMAN_SESSION_REQUIRED` | `src/backend/app/api/v1/promotions.py:56-71` | 代码 |

**代理结论（供用户审）**：

1. **有证据的**：仓库内存在「编排者称已用管理员密码会话做过 decision」的**文字记录**；代码层 G7 decision **可以**强制「人类密码登录会话、拒 Bearer」。
2. **没有证据的（本代理未见到）**：用户本人对 H-01/S-01 **逐条**核对卡片原文↔规则的可追溯勾选/批注；架构师对 plan:996/3628「禁止代批」的条文修订。
3. 因此对照 plan.md:996「由用户本人以管理员身份**逐条核对**…后批准」——在**缺少用户本人逐条核对证据**的前提下，代理初核为：**不满足**将该 13:12:55 记录等同为已完成的 G7。
4. **系统能证明 / 不能证明**：`password_login` 人类会话只能证明「当时请求来自密码登录的管理员会话」（promotions.py:56-71），**不能**证明「已逐条完成原文↔规则核对」。人类会话 ≠ 逐条核对。

---

## 4. 改到 `simulating` 还缺哪一步

> T-R47 按 T-A109 §2/§6 改写 B、C 行与关键路径；T-R41 原 B 行为「用户本人逐条核对并在 UI 批准 G7」（历史）。

| 步骤 | 要求 | 当前（代理只读） |
|---|---|---|
| A | G1–G6 自动门禁无 `fail`；warn 须 ack（T-A109 §5 步骤 A：编排者在目标环境管理页只读抄录 `gate`/`result`/`stale`，不抄 detail、股东代码或持仓，T-A83 口径） | **仍未决**：本报告未查询库内 `gate_results`（红线不读库） |
| B | 研究员核对稿缺证据为 0 → 架构师复核 → 编排者引用覆盖该卡的用户本人授权、以管理员可信交互会话代批并留证（T-A109 §2） | **未满足**：仍缺证据 1 项（S18，须用户本人答复，§6；T-R53b 后，T-R55 按 v2 重核不变）+ 步骤 A；另有代批前置（不计入 40 项）：S-01 v2 导入 + G1–G6 重跑（T-R55；库内 v1 审核（055105a）作废）；H1 部署后 seed 与只读 SQL 验证（导入侧 2→3 已落于 main 00538a1，§6 H1 前置行，T-A116 ③、T-A119 ②③）。H4 已经架构师 T-A115 复核；H14/H16/H17/H18/S14/S16/S3 已经架构师 T-A111 复核（H16/H18 已由 T-A116 :4 对 v3 复核通过），其余「一致」项未见逐项复核结论 |
| C | 编排者 `POST .../lifecycle` `{to:simulating, review_id, password}`；审核须 approved、非 stale、哈希一致；同可信会话+密码（T-A109 §6） | **未执行**（红线：本单不改 lifecycle） |
| D | 晋级后仅模拟候选信号、标「模拟中」、不生成计划草案 | 取决于 C |

**剩余关键路径**：补齐 §6 → 架构师复核 → 编排者按 T-A109 §6 代批留证 → lifecycle（api-contract.md:953 decision 与 :960 lifecycle；T-B80 plan.md:3632）。脚本与未获授权的代理不得代填密码、不得代点批准。

其他前置：若 G2/G6 对某字段仍为 declared/警告，以当时门禁报告为准（本文件不臆测库内状态）→ 标「缺证据」。

---

## 5. 计数（代理初核，供报告汇总）

| 卡 | 项数 | 一致 | 不一致 | 缺证据 |
|---|---|---|---|---|
| H-01 | 20 | 20 | 0 | 0 |
| S-01 | 20 | 19 | 0 | 1 |
| 合计 | 40 | 39 | 0 | 1 |

（T-R55 按 S-01 v2 重核 S1–S20 后仍为 39/0/1，无升降；库内 v1 审核（055105a）作废，S-01 v2 导入 + G1–G6 重跑列为代批前置，不计入 40 项。T-R53b 后 39/0/1：H12、S12 按 T-A118 ②③ 与 team 报告 T-R53-dbproof（:372 由合并门禁在 o61 亲跑并篡改自证）改一致，只缺 S18；编排者裁定不采信 T-T68、改由合并门禁亲跑。T-R53 时 37/0/3：S20 按 T-A118 ② 改一致；H12、S12 改引生产用例，但 service.py:355 调用点直接绕过本角色未能亲证（需 o61 库例），按编排者 T-R53 口径暂不改；若编排者采信 T-T68 的 o61 实跑，两项改一致后为 39/0/1（T-A118 ⑫ 预期），只缺 S18。T-R50/T-R52 时 36/0/4，同 T-R49；T-R48 时 35/0/5，T-R46 时 34/0/6。H4 计入「一致」：架构师 T-A115 :3 复核确认一致、:4 计数 36/0/4 与本表相同；若 H4 不计入一致，则为 35/0/5。T-R50 按 v3 重核 20 个 H 行，无状态降级；H16/H18 经架构师 T-A116 :4 对 v3 复核通过（T-R52）。用户勾选全部默认未勾；最终以架构师复核与系统审计为准。H14/H16/H17/H18/S14/S16/S3 已由架构师 T-A111（团队报告，不入库）:4–:10 复核通过（T-R48 同步）；其余标「一致」的项未见架构师逐项复核结论，保持原状。**§4 步骤 A（库内 G1–G6 结论，编排者只读抄录）不在 40 项内，仍未决**，故代批前提「缺证据为 0」尚不满足。）

---

## 6. 仍缺证据 1 项（S18）+ 步骤 A + H1 部署前置 + S-01 v2 导入前置（T-R53b 后，T-R55 增 S-01 v2 前置；H4 架构师复核通过，T-A115 :3）：缺什么、谁补（T-R47，对照 T-A109 §5）

| # | 缺什么证据 | 谁能补 | 需麦蕊实调 | 需用户本人决定 | 补后复核 |
|---|---|---|---|---|---|
| H4 | （已补，T-R49）v3 落卡：证伪口径量化（F1/F2，`cards/hold_risk_monitor.md:128-151`）、集中度改风险限额（:40、:23），缺口记 gaps :153-158；见 §1B | 策略研究员 | 否 | 否 | 架构师复核通过（T-A115 :3） |
| H12 | （已补，T-R53/T-R53b）生产用例见 H12 行（main 00538a1）；service.py:355 库例 T-T66 :372 由合并门禁在 o61 亲跑并篡改自证（team 报告 T-R53-dbproof）；残留：需 o61 库，离线不覆盖 | 测试 / 编排者（o61 门禁） | 否 | 否 | 架构师（T-A118 ③） |
| S12 | （已补，T-R53/T-R53b）a/c/d/e 本角色亲证；b) bse 运行侧门闩同 H12，库例 :372 见 T-R53-dbproof；残留：需 o61 库，离线不覆盖 | 测试 / 编排者（o61 门禁） | 否 | 否 | 架构师（T-A118 ②） |
| S18 | 用户本人对「E1 改绝对涨幅、X4 未进 v1」（卡头:6 ①②）是否接受的答复，记入本稿 | 编排者向用户本人确认；产品取舍，不在 2026-11-09 代办字面范围内 | 否 | **是** | 架构师 |
| S20 | （已补，T-R53）T-T63 :364/:407/:414、T-T46 :277（main 00538a1；screen.py:39/:42 篡改均失败） | 测试 | 否 | 否 | 架构师（T-A118 ②） |
| H1 前置 | 代批前置，不计入 40 项，H1 状态不变。**导入侧已落（T-R53 核实，main 00538a1）**：`config/engine_policy.yaml:2` 顶层与 :18 hold_risk_monitor 版本号均为 3（T-B121）；`src/backend/selfchecks/test_tb71_import.py:163` 离线覆盖 T-A119 ② (a)–(d)（T-B122），本角色亲跑通过，engine_policy 改回 2 时失败；原 :65/:238/:244 写死 2 的断言与字面已由 T-B121 改为按 key 查写死的期望表（H-01 为 3、W-01 为 2）：:65 现为 :70-73（期望表在 :72），:238/:244 现为 :292/:298；均为库例，需隔离 PG（T-R55b 按 bb27e71 核实）。**剩余（部署侧，T-A119 ②③）**：部署后在 worker 容器内显式跑 engine_policy seed，并用只读 SQL 核对（`deploy/runbooks/wrapup-deploy.md:202-251` seed 节、:257 起只读 SQL 清单，T-O73）：hold_risk_monitor 的 strategy_versions 最大版本号为 3 且 G7 审批对象是该行；持仓实例绑定 v3 行；engine_policies 最新行为 3；首条新建议记录的政策版本号为 3。正式卡 v3 导入（:253）在 runbook 中仍为「待补」 | 运维（runbook）/ 编排者（部署后只读核验） | 否 | 否 | 架构师 |
| S-01 v2 前置 | 代批前置，不计入 40 项。**S-01 v2 导入 + G1–G6 重跑**（T-R55，编排者裁定）：库内 v1 审核（055105a）作废；v2 须经导入器导入为新版本行（不可覆盖库内 v1，同号改内容会被拒），再在 v2 上重跑 G1–G6，并新建针对 v2 的 G7 审核；库内 gate_results 的只读抄录放到收口部署后的只读 SQL 里做。runbook `deploy/runbooks/wrapup-deploy.md` 目前只写了正式卡 v3 导入「待补」（:94、:253），未含 S-01 v2 导入步骤；仓库内写死处盘点见 `T-R55/inventory.md`（只列不改） | 后端/运维（导入）、编排者（部署后只读 SQL） | 否 | 否 | 架构师 |
| A | 库内 G1–G6 `gate`/`result`/`stale`（无 fail、warn 已 ack） | 编排者在目标环境管理页只读抄录（T-A83 口径） | 否 | 否 | 架构师 |
| S3 | （已补）T-R47 语义审核 §2A | 策略研究员 | 否 | 否 | 架构师复核通过（T-A111 :10） |

---

*文件路径：`docs/strategies/T-R41/g7_review_H-01_S-01.md`｜任务 T-R41｜代理准备；T-R42 仅更新「代理初核/当前证据/§5 计数」列；T-R43 按 T-A83 修 B-1 与 L-1..L-6（H18 改回缺证据，计数 32/0/8）；T-R44 按 T-A85 L-1 补 S13 引用、按 T-T46 改 H17 为一致（计数 33/0/7）；T-R46 按 T-T48/T-A86 改 H18 为一致（计数 34/0/6）；T-R47 按 T-A109 同步 G7 程序表述、做 H4/S3 语义审核（S3 改一致待架构师复核，计数 35/0/5）、新增 §1A/§2A/§6，T-R48 按 T-A111 同步 H14/H16/H17/H18/S14/S16/S3 为架构师复核通过、核实 H17 提交关系、H4 加 v3 差异稿指针（仍缺证据，计数 35/0/5），T-R49 按 T-A112 落 H-01 v3、H4 改一致待架构师复核（计数 36/0/4）、新增 §1B 与 v3 行号影响说明；T-R50 按 v3 重核全部 20 个 H 行行号与结论、H4 按 T-A115 :3 改架构师复核通过（计数 36/0/4）、新增 §2B 记 S-01 universe.pool 口径 gaps（T-A114 ②）；T-R51 按 T-A116 ① 改 H15 fixtures 起始行；T-R52 按 T-A116 ② 改 H16/H18 为架构师对 v3 复核通过、§4/§6 补 H1 代批前置（T-A116 ③，计数仍 36/0/4）；T-R53 基 main 00538a1 拣入 T-R51/T-R52（96e90a6 作废），按 T-A118 ③、T-A119 ④ 改 H12/S12 引生产用例（:355 库例未亲跑，暂缺证据）、S20 改一致、H1 前置改为导入侧已落、清 :47/:68 v2 残留（计数 37/0/3）；T-R53b 按 team 报告 T-R53-dbproof 把 H12、S12 改一致（计数 39/0/1，只缺 S18）；T-R55b 补 H1 行与 §6 H1 前置的 test_tb71_import.py:72 并更正 :292/:298 转述、§2B SG1 注明 universe.pool 推迟到 v3 待用户决定（计数仍 39/0/1）；T-R55 按编排者裁定 S 行改指 S-01 v2、写明库内 v1 审核（055105a）作废、§6 加 S-01 v2 导入 + G1–G6 重跑前置、新增 §2C 逐行重核（计数仍 39/0/1），用户勾选仍未勾*
