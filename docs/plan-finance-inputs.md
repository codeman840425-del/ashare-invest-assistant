# T-A199：B9–B12 后端实现方案

依据：`docs/contracts/finance-inputs.md`（#225，T-A197，F-Q01–09 均为 Opt-A）。本方案只新增本文，不代表功能已实现。
模块路径除特别注明外相对 `src/backend/`；下文「新建」包括拟增模块、函数、测试文件及 JSON 键，均未实现、未验证。
核查仅依据仓库代码与迁移，未连接数据库，表内实际行数、历史覆盖及来源响应均为「未验证」，不把建表等同已有可用数据。
研究基准目录 `docs/strategies/T-R86/` 由 PR #249@77dc09d（分支 `docs/T-R86r`，未合入）交付；合入前以该 head 的 README 与 `reference_values.csv` 为准。本次离线读取的 `.codex-input/README.md`、`.codex-input/reference_values.csv` 已与该 head 逐字节核对一致，不将交付文件复制进本分支，不改该目录。
全程离线；不读写 `.env`、密钥或私有样本，不运行外呼探针，不真调麦蕊、不回填、不提交、不 push。
新增数据或补齐证据按实际操作区分：离线已有数据、合成输入、补证整理不属于真调。依 TEAM-RULES 第二节，仅硬红线须用户本人批准：真调麦蕊（日K、分钟、单 D）、生产部署、删除用户数据、对外发送、解除 HALT、恢复外网出口、`backfill --apply`。通达信真实全量导入已由用户 11-14 t1110u 授权，仍须走 `upsert_daily_bars` 并过写库门闩；本 PR 不执行采集或回填。

## 一、现状与缺口

| 可复用结构／入口 | 已核实的字段、行为与支撑范围 | 缺口／限制 |
| --- | --- | --- |
| `app/db/tables/market.py` 的 `market.financial_reports` | `id,code,report_type,period_end,payload,payload_hash,announce_date,available_from,first_seen_at,last_seen_at`；按代码／类型／报告期／哈希唯一，可留多版本 | 无独立发行人、股份类别、替代链、可比链、覆盖证明；真实内容未验证 |
| 同文件 `market.factor_values` | `code,trade_date,factor_id,value,calc_version,fetched_at,available_from,first_seen_at` | 主键仅前三项，无 JSON／单位／依赖证据；同日同因子不能留多版，不足以证明 B10–B12 主源 PIT |
| 同文件 `market.raw_payloads` | `id,endpoint,params_hash,fetched_at,status,body,body_hash,pinned` 可承载原始证据 | 没有独立所有者／证书列；注释约定未固定数据保留90天，实际清理链未验证，须显式固定依赖 |
| 同文件 `market.market_events`、`market.announcements` | 前者有 `id,code,type,event_date,payload,first_seen_at,original_url,source`；后者有 `published_at,url,first_seen_at` | 事件 `source` 仅允许 `rule/llm`；公告与除息线索不等于支付完成、最终决议或年度完整覆盖 |
| 同文件 `market.securities`、`market.security_code_history` | `list_date,list_date_basis,exchange,board,field_sources`；换码表有 `code,old_code,valid_from,valid_until,source,recorded_at` | 尚无契约发行人身份链；上市日是否为交易所上市边界、转板连续性均未验证 |
| 同文件 `market.trading_calendar`、`market.ex_rights_events` | 日历 `date,is_open`；事件 `code,ex_date,cash_per_share,snapshot_sha256,registered_at` | 日历表本身无覆盖／来源证明；除息现金不能证明发放日、归属年、支付完成或股份类别 |
| 同文件 `market.feature_bars_daily`；`app/db/tables/reviews.py` 的 `app.data_snapshots` | 特征表 `values,feature_set_version,computed_at`；快照 `items,known_events,hash,user_id,licence_id,purpose` | 计算时间不等于可见时间；快照注释为不可变，用户级 horizon/candidate 必须有 `user_id` |
| `app/features/pipeline.prepare` | 已接受 `as_of,scalars,registry`，核对单位、过滤可见时间 | 财务标量缺专门的版本、语义与依赖校验；`factors` 参数是复权因子，不是财务主源 |
| `app/strategy/horizon/inputs.collect/evidence/snapshot_id` | `collect` 当前使用现在时点，四个财务键未赋值；证据从 `sources` 输出；快照 ID 仅哈希版本、代码及值 | 无显式评估 d/as_of；同值不同财务依赖尚不能区分快照；不能沿 `_src` 的时间兜底伪造财务可见性 |
| `app/api/v1/security_financials.py`、`security_factors.py` | `PlaceholderFinancialsReader.read`、`PlaceholderFactorsReader.read` 均读空数据集；`factors` 另有禁止合成行／版本的守卫 | 财报响应的 `roe_pct` 不能当 TTM；因子 API 仍应保持占位，不借本方案开放正式值 |
| `app/reports/dimensions.financial_pit`；`app/financial_basis.TradingCalendar.next_day` | 前者检查披露、日历连续性、次开市日09:30与首见；后者严格取覆盖内下一开市日 | 前者不证明公式／全部依赖，后者依赖显式覆盖与来源；不能从自然日推断 |

迁移核对：`migrations/versions/0001_baseline.py` 已建财报、因子、原始响应、事件、日历、特征和快照表；`0017_t_b49_snapshot_purpose.py` 已允许 horizon 快照，输入模块关于缺该 purpose 的旧注释已过时。
`app/db/tables/strategy.py` 的 `app.symbol_horizon_assessments` 已有 `snapshot_id,inputs_missing,caps,evidence,hints`；`app.candidate_versions.snapshot_id` 已在 `app/db/tables/research.py` 定义。
在 `src/backend/app` 检索财报／因子／原始响应／事件表名，仅发现表声明，未找到这些表的生产读写接线；不宣称已有导入或重算任务。

数据来源仅限下列麦蕊既有接口名及上列已建落库表，不增加供应商或新接口：

| 已有代码位置 | 麦蕊接口名／字段线索 | 对 B9–B12 的意义与未验证项 |
| --- | --- | --- |
| `probes/p05_fundamental.main`、`p11_gaps.item3_plrq`、`p13_fin_pit.call_plan` | `/hsstock/financial/income`、`balance`、`cashflow`、`pershareindex`、`capital`；`jzrq,plrq`，利润 `gsmgsyzzdjlr`、权益 `gsmgdqsyhj` | 可提供报告期、归母利润／权益线索；币种单位、覆盖、重述桥接与正式报告分类未验证；capital 不能替代归母权益 |
| `probes/p06_factors.main`、`p11_gaps` 的 `DOC_FACTORS` | `/factor/quality` 的 `roe_ttm`、`/factor/growth` 的 `profit_cagr_3y`、`/factor/dividend` 的 `dividend_continuous_years`；另有 `/factor/list`、`categories`、`all`、`history`、`batch` | 三个正式主源及元数据线索；单位、年报窗口、历史 PIT、支付／闭合映射均未验证，缺证正式值为 null |
| `probes/p13_fin_pit.call_plan`、`p13_analyze.dividend_events` | `/hscp/jnfh`；分析函数读取 `give,change,cdate,sdate,line,rdate`，只抽送转事件 | 不足以证明现金金额、实际支付、归属年或全部事件覆盖；B12 支付／闭合证据缺口仍在 |

`p11_gaps.analyze_fin_rows` 统计披露与重复行；`classify_pit` 用披露后窗口作必要不充分判据；`batch_asof` 可接受响应层日期；`compare_history` 比较历史改写，均非契约的完整证明。
`p13_analyze.analyze/main` 是旧离线分析入口，已有现金流 TTM、版本差异、币种单位检查及除息线索，不是归母 ROE／CAGR／支付完成实现。
`p13_fin_pit.main` 经 `_save` 调外部接口并写 manifest；仅阅读其代码，本任务不运行。补充数据或证据遵循前述边界：离线已有数据、合成输入、补证整理不归为真调；若需真调麦蕊或执行 `backfill --apply`，须用户本人批准。

## 二、存储与计算边界：优先零迁移

本方案不新增表、列、索引或迁移；复用现有 JSON，新增键须带独立格式版本并由 PR1 校验，旧格式缺证保持 null，不补造历史。
- `financial_reports.payload` 保留原业务内容；`id→version_id`、`period_end→jzrq`、`announce_date→plrq`，映射须验证，不默认同义即合格。财报变化仅追加，禁止覆盖旧 payload、首见或可见时点。
- `raw_payloads.body` 留存不改写的原响应；`endpoint` 使用既有接口模板，禁止含证书；`body_hash` 校验原始内容。重述／因子每次观察分别留存，`factor_values` 只作当前缓存候选，不承担版本真相或正式准入。
- 新建 JSON 证据包置于 `data_snapshots.items`：保存 `issuer_id,security_class,version_id,source_url,content_hash,supersedes_id`、原始响应／财报 ID、来源归属、身份链、覆盖起止／截止／缺口、规则快照、可比链及依赖可见时点；用已有 `purpose='report'` 存证据包，horizon/candidate 冻结消费结果。
- 新建 JSON 证据字段含 `accounting_basis_id,consolidation_scope_basis,profit_type,currency,unit,restatement_chain_id`；规则含 `exchange,board,report_kind,rule_version,article,effective_from/to,applicable_periods,rule_evidence_at`，仅期限审计，不造披露日；来源仍须指向已存证据。
- B12 新建规范化事件 JSON 放 `market_events.payload`，按契约四元事件键与版本追加；`source='rule'` 仅表示解析，原麦蕊证据通过引用保留，不伪称已有支付事实。新建支付、批次、决议、闭合、归属字段；缺证不闭合。
- 原始表无所有者列，必须经 `data_snapshots.user_id/licence_id` 及新建 JSON 来源归属核对授权后读取；来源不可证则拒绝，不能跨用户拼接。所引用原始响应设置 `pinned=true`，保留旧快照依赖。
- 新建结果包统一为 `value,unit,available_at,dependency_version_ids,null_reasons`；原证据、正式主源结果、离线重算／对照分开存于 JSON。派生缓存复用 `feature_bars_daily.values`，新建版本标识包含依赖包哈希，禁止覆盖同版本旧结果。
- 候选沿 `app/research/content.write_snapshot` 写不可变快照；财务内部原因保存在证据包，不扩公开原因码枚举，不向公开 Evidence 强塞内部字段；对外只投影已有结构允许的字段。
- 统一 `t=min(as_of,d收盘时刻)`，均为带时区瞬时；财报可见下限为披露次开市日09:30、真实首见及全部依赖的最大值，日历覆盖不足为 null。最新有效版本冲突／缺链即拒绝，不能退旧值避开缺证。
- B10/B11 金额以 Decimal 保留精度，仅最终 pct 用 `ROUND_HALF_UP` 到两位；B9/B12 为非负整数。B10–B12 主源缺证始终 null，离线值不能补位，B10 不切 F44。
- B9 按 `doc_type∈{Q1,H1,Q3,FY}`、`period_end≥exchange_list_date`、`plrq≥exchange_list_date` 筛选。期限审计按年／半年／Q1／Q3 期末加4／2／1／1个日历月，Q1 核验不早于上年年报，特别延期须绑定适用证据；期限不得替代真实披露。
- B10 离线公式为 `100×TTM(P)/((E(P)+E(P−4))/2)`，其中 `NP=income.gsmgsyzzdjlr`、`E=balance.gsmgdqsyhj`；B11 为 `100×((NP_FY(y)/NP_FY(y−3))^(1/3)−1)`，两个完整年报端点严格正、跨度36个月且上市满三年。
- B12 新建事件证据字段包含 `plan_id,payment_tranche_id,cash_per_share_gross,cash_pay_date,completion_evidence_url,completion_seen_at,payment_status,distribution_fiscal_year,event_kind,event_type`；可见时点取发放日当地日终、实施安排与完成证据可见时点之最大值。
- B12 闭合须年报、年度最终决议、全部中期／特别／年度事件覆盖，已知方案全部完成或最终取消；从 Y 向前统计闭合正现金年，遇明确零年终止，未知或缺零中断年为 null。只按目标普通股税前人民币现金，不由回购总额反造股利。

不设动表 PR：目前可通过追加证据包满足留存；JSON 查询性能、固定策略、并发幂等及保留机制仍未验证，PR1 须验证。若发现必须动表，先另列具体表／字段／理由／回滚的修订方案，不在本任务预设迁移。
零迁移回退：停止新导入／重算接线，恢复财务缺证路径与 API 占位；保留已有不可变包、版本、原始证据及引用，不删历史、不重写旧快照。

## 三、T-B176 内的拆分 PR1–PR6（按依赖顺序）

正式承接任务为 T-B176（后端，依赖 T-A199 方案合入），负责下列全部实现、接线与逐入口验收。方案引用 `tasks/T-A199.md`，验证引用 `tasks/T-R86.md` 与 `reports/T-R86.md`；T-A199 仅交方案，不算实现已派单（L-046）。下文 PR1–PR6 均指 T-B176 内的拆分 PR1–PR6。

净增行数为实现加测试及 CI 登记的估算，每个 PR 均不超过800行；超出须再拆，不能省略入口验收。下列测试文件全部「新建」。
每个新增测试文件必须同 PR 登记 `tests/ci-groups.yaml` 的 `file/group/keywords/unverified`；未验证资源风险须串行并写原因，不得提前登记不存在文件。

| PR／前置依赖／预计净增 | 模块与函数范围 | 新建测试文件与 CI 分组 |
| --- | --- | --- |
| T-B176 内的拆分 PR1 证据与版本；无；780行 | 新建 `app/features/finance_evidence.py`：新建 `save_receipts/load_receipts/select_versions/cutoff`，离线导入、来源隔离、哈希、追加、固定依赖；复用 `TradingCalendar.next_day`，补 `reports/dimensions.financial_pit` 全依赖可见校验 | 新建 `tests/backend/unit/test_ta199_receipts.py`（parallel：纯函数／替身）；新建 `tests/backend/integration/test_ta199_storage.py`（serial_pg：隔离真实数据库） |
| T-B176 内的拆分 PR2 B9–B11；PR1；790行 | 新建 `app/features/horizon_financial.py`：新建 `count_reports/roe_ttm/profit_cagr_3y`，覆盖／身份／期限审计、TTM、端点及可比链；新建 `app/features/horizon_vendor.py`：新建 `adapt_vendor`，先实现 B10/B11 主源准入 | 新建 `tests/backend/unit/test_ta199_financial.py`（parallel：合成输入） |
| T-B176 内的拆分 PR3 B12；PR1、PR2；790行 | 新建 `app/features/horizon_dividend.py`：新建 `confirm_payment/close_years/cash_only/run_years/ex_date_proxy/cash_distribution_plus_buyback_years`；扩展 `horizon_vendor.adapt_vendor` 的 B12 校验，离线对照单独命名 | 新建 `tests/backend/unit/test_ta199_dividend.py`（parallel：合成事件） |
| T-B176 内的拆分 PR4 统一接线；PR1–3；790行 | 修改 `pipeline.prepare`、`horizon/inputs.collect/evidence/snapshot_id`、`classifier.classify`、`api/v1/horizon.get_horizon_assessment`；新建 `app/features/finance_jobs.py` 及新建 `recompute_job`，只重算已存证据，不外呼 | 新建 `tests/backend/unit/test_ta199_horizon.py`（parallel：替身）；新建 `tests/backend/api_app/test_ta199_horizon_http.py`（serial_pg：鉴权请求与存档） |
| T-B176 内的拆分 PR5 候选与资源入口；PR4；790行 | 修改 `research/content._fit/generate/write_snapshot`、`api/v1/candidates._new_version/create_candidate/create_version`，传同一内部 d/as_of；核验两类 `Placeholder*Reader.read` 及 `financials/factors` HTTP，占位守卫保留 | 新建 `tests/backend/api_app/test_ta199_finance_entries.py`（serial_pg：原鉴权／版本链／HTTP） |
| T-B176 内的拆分 PR6 探针与演练边界；PR1–5；780行 | 核验 `probes/p06_factors.main`、`p11_gaps.analyze_fin_rows/classify_pit/batch_asof/compare_history/main`、`p13_analyze.analyze/main`；增加 `p13_fin_pit.call_plan/main` 离线防外呼验收；分别执行既有 SQL／恢复脚本 | 新建 `tests/backend/unit/test_ta199_probes.py`（parallel：传输替身／临时文件）；新建 `tests/backend/integration/test_ta199_drill.py`（serial_pg：隔离演练库／容器，资源风险未验证） |

PR4 的 horizon HTTP 用请求时点和评估交易日生成内部截点，不新增公开查询参数；PR5 的财报日期查询须明确日终解释并再受评估收盘截点约束，不把日期猜作公告盘前瞬时。
PR6 复查 CLI／Windows／SQL 执行链，新增入口必须逐一补验收；不得用 Linux 纯函数通过代替 Windows 或 SQL 会话通过。

## 四、验收清单

以下测试名均为建议新建、未验证；沿用契约 `test_ta197_` 名便于对账，其余为 `test_ta199_`。各条均需记录实现版本、平台、通过／失败／跳过；未执行写「未验证」。
同一份明确标为虚构的合成包包含财报／因子／事件版本、身份、规则、日历、闭合证明及固定 d/as_of，各格式由它派生。正常、边界、缺数、依赖晚于 t、等价时区、新版本不改旧时点为每个适用入口的参数场景。
数值回归基准统一取 PR #249@77dc09d 的 `docs/strategies/T-R86/reference_values.csv`；依据同目录 README「验收用途（编排者 T-R86c 裁定）」分层验收，不把合成值冒充研究基准。

**基准分层**：主值列为 `value`，空值原因列为 `null_reason`（分号分隔），单位列为 `unit`；代理层列为 `proxy_value`，另有 `proxy_available_at`、`proxy_flags`。README 已明确代理层是后端计算逻辑的验收基准，仅用于离线验收，不是麦蕊真值，不能作为生产主值，也不得替换契约主源；不据此引入真调。

- `test_ta199_ref_formal_null` 按每行 `code/as_of/feature` 对照：240 行 `value` 均为字面量 `null`，正式输出须为 null，内部 `null_reasons` 按 CSV `null_reason` 拆分后的原因码集合断言，不能仅检查非空。`available_at` 也全部为 `null`，不以代理时点补正式可见时点。
- PR2/PR3 的 `test_ta199_ref_proxy_b9`…`_b12` 在同一份输入下逐行核对 `proxy_value`：非空项作数值相等断言；B9 为整数，B10/B11 按 README 仅在最终 `ROUND_HALF_UP` 到 pct 两位后比较。容差以 README「逐值一致」为准，不自行放宽；README 未另列绝对／相对容差，此类额外容差为「未验证」。空项断言 null，保留 `proxy_flags` 中的缺证说明，不把 null 当0，也不跳过空行。
- B12 的主值与代理值均全空，不能从本 CSV 提取非空数值样例或验证连续年数的非空数值路径；按 README 用标为【虚构】的合成夹具另验 F-Q06–F-Q09 边界，不把夹具值写成研究样例。`ex_date_proxy_years`、`cash_distribution_plus_buyback_years` 是独立对照列，在 B12 的60行也均为 `null`，不填入 B12。

**覆盖与列名出处**：以下统计、原因码及各 B 项样例均取自该 head 的 `reference_values.csv` 表头及相应列；代理算法、舍入与验收用途取自 README。全表240行，B9–B12 各60行，均为同一20代码×3个 `as_of` 的完整组合（代码按字符串保留前导零）：

- `code` 集合：`000001,000972,001225,001246,001381,300502,300750,301569,301718,600228,600293,600519,600825,603159,603307,688610,688801,688981,920000,920085`。
- `as_of` 集合：`2026-06-30T15:05:00+08:00`、`2026-09-30T15:05:00+08:00`、`2026-11-09T15:05:00+08:00`。README 规定各日统一按当日15:00截止；代理时点使用指数观察日与首K等代理，历史 PIT 仍未验证。

| `feature`／`input_key`／`unit` | 主值 `value`／`null_reason`（每项60行相同） | 代理层 `proxy_value` 形态与非空／null行数 |
| --- | --- | --- |
| B9／`f.fin_report_count`／`count` | `null`／`missing_visibility;coverage_unknown;identity_unknown` | 按报告期去重计数的整数代理；41／19 |
| B10／`f.roe_ttm`／`pct` | `null`／`missing_visibility;source_semantics_unverified;unit_unverified;incomparable_basis` | 归母 ROE TTM 的两位 pct 代理，可为负；38／22 |
| B11／`f.profit_cagr_3y`／`pct` | `null`／`missing_visibility;source_semantics_unverified;unit_unverified;incomparable_basis;identity_unknown` | 三年年报端点 CAGR 的两位 pct 代理，可为负；26／34 |
| B12／`f.dividend_continuous_years`／`years` | `null`／`missing_visibility;source_semantics_unverified;payment_unconfirmed;year_unclosed;coverage_unknown;no_known_break` | 全部 `null`，缺支付完成、年度闭合、覆盖与明确中断证据；0／60 |

### B9：报告期数

参考样例（列名及单元格逐字取自 `reference_values.csv`，未换算）：

| code | as_of | feature | value | proxy_value | unit |
| --- | --- | --- | --- | --- | --- |
| 600519 | 2026-06-30T15:05:00+08:00 | B9 | null | 96 | count |
| 000001 | 2026-06-30T15:05:00+08:00 | B9 | null | 115 | count |

| 测试名／PR | 场景 | 期望 |
| --- | --- | --- |
| `test_ta197_b9_count`／PR2 | 全历史上市后正式 Q1/H1/Q3/FY 利润表；超过最近12行；换码／转板／ST／停牌 | 按报告期去重非负计数；身份需证，不因换码／状态重置，不截最近12行 |
| `test_ta199_b9_scope`／PR2 | 上市前、招股／挂牌／预告／快报／摘要、比较数、占位 `plrq≤period_end`、更正重复 | 排除不合格项，更正不增期；B9 排除不限制 B10/B11 独立合格依赖 |
| `test_ta199_b9_evidence`／PR2 | 缺上市日／身份、缺覆盖／披露／首见／日历；完整空集合；规则未知／逾期 | 对应内部原因且 null；完整空集合才为0；规则不明仅审计，影响范围才置空；期限不造公告日、逾期不删报告 |

### B10：归母 ROE TTM

参考样例（列名及单元格逐字取自 `reference_values.csv`，未换算）：

| code | as_of | feature | value | proxy_value | unit |
| --- | --- | --- | --- | --- | --- |
| 600519 | 2026-06-30T15:05:00+08:00 | B10 | null | 31.26 | pct |
| 000001 | 2026-06-30T15:05:00+08:00 | B10 | null | 8.20 | pct |

| 测试名／PR | 场景 | 期望 |
| --- | --- | --- |
| `test_ta197_b10_vendor`／PR2 | quality 主源单位、窗口、归母语义、依赖／历史 PIT 缺证；已证负值 | 缺证 null／保留原因，合法负值保留；不切 F44、不用离线值补位 |
| `test_ta197_b10_recompute`／PR2 | 年报与非年报 TTM；缺分量／不足12个月；期末／平均权益非正；期初负但期末与平均正 | 按契约 `NP_YTD+上年NP_FY−去年同期NP_YTD`，年报直接取全年；权益边界准确，不相加四份累计数 |
| `test_ta199_b10_basis_rounding`／PR2 | 混币种／单位、非有限金额、重述基础不齐；桥接证据后见；舍入边界 | 不可比／缺证 null；桥接只从自身可见后生效，正常并购不自动剔除；中间不舍入，最终 pct 两位半入 |

### B11：归母利润三年 CAGR

参考样例（列名及单元格逐字取自 `reference_values.csv`，未换算）：

| code | as_of | feature | value | proxy_value | unit |
| --- | --- | --- | --- | --- | --- |
| 600519 | 2026-06-30T15:05:00+08:00 | B11 | null | 9.49 | pct |
| 000001 | 2026-06-30T15:05:00+08:00 | B11 | null | -2.16 | pct |

| 测试名／PR | 场景 | 期望 |
| --- | --- | --- |
| `test_ta197_b11_vendor`／PR2 | growth 主源年报锚点／归母利润／单位／历史 PIT 未证 | null／保留原因；离线算出也不能替代正式主源 |
| `test_ta197_b11_recompute`／PR2 | 最新可见完整12个月年报 y 与 y−3；正端点、零／负基期、零／负／缺末期 | 用36个月三次方根公式；分别输出契约空值原因，零末期不输出负百分之百 |
| `test_ta199_b11_span_basis`／PR2 | 上市不足三年／身份未知、会计年度变更、缺端点、未来年报／较旧可算组合、中间两年缺失 | 对应 null，不退旧 y、不变两年／TTM；不强制中间两年进公式，端点仍须可比，最终才舍入 |

### B12：现金分红连续年数

参考空值样例（列名及单元格逐字取自 `reference_values.csv`，未换算；该项没有非空数值，不能编造数值样例）：

| code | as_of | feature | value | proxy_value | unit |
| --- | --- | --- | --- | --- | --- |
| 600519 | 2026-06-30T15:05:00+08:00 | B12 | null | null | years |
| 000001 | 2026-06-30T15:05:00+08:00 | B12 | null | null | years |

| 测试名／PR | 场景 | 期望 |
| --- | --- | --- |
| `test_ta197_b12_vendor`／PR3 | dividend 主源缺支付／闭合映射；非整数／负数／单位不符 | 正式值仅已证非负整数 years；否则 null，不用本地事件补主源 |
| `test_ta197_b12_payment`／PR3 | 预案、发放日未终、完成证据晚见／缺失、延期、最终取消、目标股份分批、更正去重 | 仅发放日日终与安排／完成证据均可见且全部目标批次完成才计；取消排除，未知不闭合 |
| `test_ta197_b12_run`／PR3 | y0 年报、最终决议前后 Y 切换、跨年支付、补派后见、未决补派／执行未知、未知归属 | 未见决议取 y0−1、见决议取 y0且不因未实施回退；按利润归属年；未决不闭合，后见只改新时点 |
| `test_ta199_b12_break`／PR3 | 无完整年度、途中未知、无明确零中断年、Y 明确零、全覆盖无现金 | 对应 `no_complete_year/year_unclosed/no_known_break` 等原因；只有明确闭合零年才为0或终止连续段 |
| `test_ta197_b12_cash_only`／PR3 | 每10股报价、中期／特别／年度、年度含中期总额、重复事件、不同股本基数、类别未知／归属不明、负现金 | 转人民币目标普通股税前每股并去重，只加本次新增；正额用于年度判别，不作收益率；异常／不可拆／缺证 null |
| `test_ta197_b12_offline_isolation`／PR3 | 纯送转、纯回购、股利加回购不可拆、股利与回购并存；除息代理及另名扩展对照 | 纯回购闭合年现金为0，并存只计股利，不可拆 null；两种对照不写 B12；扩展按支付自然年／人民币总额／批次去重且缺证 null |

### B9／B10／B11／B12 共用的逐入口验收映射

本表是上述四组的共同验收项；每个列出的测试均独立执行原入口，不能以公共函数测试替代。覆盖契约末节全部入口。

| 测试名／PR | 原入口与场景 | 期望 |
| --- | --- | --- |
| `test_ta197_ingest_versions`／PR1 | 新建 `finance_evidence.save_receipts/load_receipts`，晚导入、更正、重复／冲突、来源隔离 | 原始版本追加且可重放；错来源拒绝；不更新旧首见，不补造可见时间 |
| `test_ta197_next_day`／PR1 | `TradingCalendar.next_day`，开休市与缺覆盖 | 严格下一开市日，覆盖不足无结果，不猜自然日 |
| `test_ta197_financial_pit`／PR1 | `reports/dimensions.financial_pit`，次交易日下限、首见／依赖晚见、缺日历 | 缺证拒绝；通过只说明可见性，不证明公式／语义 |
| `test_ta197_pipeline`／PR4 | `pipeline.prepare`，标量绕过拒绝、同包依赖 | 统一版本和最大可见时点；拒绝未准入的财务主源 |
| `test_ta197_collect`／PR4 | `horizon/inputs.collect`，显式内部 d/as_of，逐字段缺证 | 四字段保留 null 与内部原因，不混入其他时点 |
| `test_ta197_evidence`／PR4 | `horizon/inputs.evidence`，值／单位／依赖投影 | 与结果一致；未知不生成伪数值或兜底时间证据 |
| `test_ta197_snapshot`／PR4 | `horizon/inputs.snapshot_id`，同包、同值异依赖、后见更正 | 同输入版本可重放；依赖区分；旧评估不变 |
| `test_ta197_classify`／PR4 | `horizon/classifier.classify`，四字段逐一 null／0／合法值 | 既有 LG0/LG0B/LG3/LG4、缺失封顶与北交所门禁不变 |
| `test_ta197_horizon_http`／PR4 | `GET /horizon-assessments` 经 `get_horizon_assessment` 原路请求 | 同包缺失、证据、评分一致，不以 collect 测试替代 |
| `test_ta197_recompute_job`／PR4 | 新建 `finance_jobs.recompute_job`，晚导入／更正／重复任务 | 只消费已存可见证据，新版追加且幂等；不外呼、不覆盖旧快照 |
| `test_ta197_fit`、`test_ta197_generate`／PR5 | 分别执行 `research/content._fit`（已填画像）、`generate` | 独立分类／候选解释均保留缺证，消费同一截点，不制造财务事实 |
| `test_ta197_candidate_version`／PR5 | `candidates._new_version` 原生成链，未知与合法输入 | 存档不把未知变0，不混用依赖版本 |
| `test_ta197_create_candidate_http`、`test_ta197_create_version_http`／PR5 | 分别执行 `POST /candidates`、`POST /candidates/{candidate_id}/versions` | 原鉴权／版本链结果与同包一致，新证据不改旧版本 |
| `test_ta197_write_snapshot`／PR5 | `research/content.write_snapshot`，null／证据／离线值 | 原存档入口保留正式结果与证据，另名离线值不填正式字段 |
| `test_ta197_financials_reader`、`test_ta197_financials_http`／PR5 | 分别执行 `PlaceholderFinancialsReader.read`、`financials` 的 GET 原入口，日期查询／空数据 | 保持占位，不冒充完整历史或以年报 ROE 冒充 TTM；未来实读仍须可见版本过滤 |
| `test_ta197_factors_reader`、`test_ta197_factors_http`／PR5 | 分别执行 `PlaceholderFactorsReader.read`、`factors` 的 GET 原守卫，合成主源／版本 | 无证明不出正式值；HTTP 拒绝合成行／版本，保留 pending/unavailable |
| `test_ta197_p11_fin_rows`、`test_ta197_p11_pit`、`test_ta197_p11_batch`、`test_ta197_p11_history`／PR6 | 分别执行 `p11_gaps.analyze_fin_rows/classify_pit/batch_asof/compare_history` | 覆盖统计／宽松窗口／响应日期／未见改写均不能升级为契约合格证明 |
| `test_ta197_p06_entry`、`test_ta197_p11_entry`／PR6 | 分别执行 `p06_factors.main`、`p11_gaps.main`，仅注入离线传输替身 | 无真实网络／证书读取；不自动补主源，不把模拟响应写正式值 |
| `test_ta197_p13_analyze`、`test_ta197_p13_cli`／PR6 | 分别执行 `p13_analyze.analyze`、`main`，同包派生临时输入 | 旧版本／除息线索不证明可比链或支付完成；CLI 独立留结果 |
| `test_ta199_p13_plan`、`test_ta199_p13_entry`／PR6 | 分别执行 `p13_fin_pit.call_plan`、`main`，替换传输／写盘／上下文 | 仅临时合成文件，禁止真调；manifest 首见不回溯成历史首见 |
| `test_ta197_drill_sql`／PR6 | 在隔离演练库实际执行 `deploy/db/drill/sample-data.sql` | 合成因子种子仅演练，不作为正式值／PIT 证明；不能拿文本检查当 SQL 通过 |
| `test_ta197_restore_drill`／PR6 | 独立执行 `deploy/scripts/db-restore-drill.sh`，隔离容器／库且不联网拉镜像 | 恢复结果与生产输入隔离；缺本地资源标未验证，不以替身冒充原脚本通过 |

## 五、风险与未验证项

- 契约 U01A–U09B 均保持「未验证」：规则历史／延期、上市边界与转板、可比桥接、主源端点及单位／窗口／历史 PIT、实际支付证据、年度闭合与特别分红归属、回购可拆分；缺证正式值 null。
- 日历表无来源与覆盖元数据；新证据包必须显式提供可信覆盖，不能因查到几个开市日就宣称完整。补证整理离线已有数据及使用合成输入作离线验证均不属于真调；若需真调麦蕊或执行 `backfill --apply`，须用户本人批准，其他操作按前述硬红线边界处理。
- 追加证据与财报唯一约束的并发一致性、原始响应固定及快照不可变触发器实际行为、来源授权与性能均待 PR1 在隔离数据库核验；本任务未连接数据库。
- `deploy/db/drill/sample-schema.sql` 的 `factor_values` 用 `security_id`／整数 `factor_id`，与生产代码表结构不同；恢复演练通过也不能证明财务语义。Windows 未发现直接计算入口，仍须 PR6 复查并记录，未执行就是未验证。
- T-R86 四组参考值已按 #249@77dc09d 回填，交付 PR 尚未合入；后端研究样本回归仍待 T-B176 实现后执行，B12 非空数值路径须用【虚构】合成夹具覆盖。方案及本任务的静态检查通过不等于功能、真实 SQL、Windows 或主源准入已通过。
