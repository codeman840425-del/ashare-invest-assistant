# S1-3：九旧文档 PR 汇总与来源保全

状态：已按 Chief 的 S1-3 专项裁定完成整合，当前待 GitHub CI；源资产远端保全后关闭九旧 PR，保留分支。
日期：2026-11-12（MST）。整合基线：`c18a74bc692bec7b9a253f4406527adb986fcca9`（PR #89）。

## 来源与适用范围

本单只承接 #78、#65、#60、#55、#47、#37、#23、#20、#10 的文档和研究资产。逐 PR、完整冻结 source head、源/目标路径与承接方式见 [来源映射](S1-3-source-map.md)。源 PR 共同基线为 `465e02046fa8d971897603742497444f884e89a2`，不能以其整份 plan/api/config 覆盖当前 main。

新增研究资产按源 blob 保全，包含 docs 内的 Python、YAML、JSON 与公开公告标题 JSONL。本单仅检查语法和身份，不运行抓取、研究回放、匹配器验收或 r2；原文中的历史测试、样本数字与已批准表述是源交付记录，不代表本次重新执行或批准。旧远端分支保留；关闭 PR 必须在汇总 PR 的远端资产核验以后执行。

## 契约合并与兼容影响

| 来源 | 合并结果与适用范围 | 兼容/实现边界 |
|---|---|---|
| #78 A-12 | 所有响应级 DataStatusBlock 的 `data_as_of` 键必有，最早非空值、全空 null；SecurityProfile 合并公开与本人证书的实际参与时点 | 旧的非空 datetime 消费者须同步；date 不拼造 datetime；Evidence 与独立事件时点不放宽。main profile 仍固定 null，属于后续实现缺口 |
| #78 SSE quote | 无变化不发新事件，发布至少一条可信变化项，顶层 `data_as_of` 非空并取实际行情最早时点 | transport 不代做 quote 校验，生产发布入口以后落实；合法历史续传照旧 |
| #78 Notification | §5.1 补 `merged_count/updated_at/refs/version`，与既有 §7.11.4 对齐；旧投影 1/created_at/[]/1 | 不新增合并/版本行为；枚举及 `/meta/enums` 前置已由旧 #14 转 #25，汇总不重复抢改该枚举 |
| #78 ST205 | 完整静态资源先于方法与动态模板，实际 dispatch 与 `Allow/details.allowed` 同源 | `/suggestions/refresh` 仅 POST；管理员隐藏 404 无 Allow、CSRF 与全局上限保持；PR #89 已含路由修复 |
| #60 T-A158 | factors `trade_date:string(date)\|null`：合法请求值透传；未指定且无批次为 null | 不造日期/版本；与 main 的真实因子集版本例外合并，不把已知集的筛选空集版本清空；客户端/schema/mock 接受限定的 null |
| #55 T-A157 | `rerun` 默认 false；true 新建一轮，旧 pending 保留；G2 记执行时目录状态，真正重跑记 `promotion.rerun` | 目标契约，实现另派；目录变化不自动失效或复活审核，不加入 content_sha256，不豁免 stale/权限/CSRF |
| #65 A-09/RV-05 | 诉讼/仲裁离线五证齐且冻结公告 ID 映射后，才有 v4 新增计数资格；查封三证齐仅研究候选 | A-09 取代 T-A156 整份；不启动 v4、不改 v3/N-01/特征等级。原 L03/L05 种子不足，后继合成五证/缺证规格随源保全，不称运行时验收 |
| #20/#10/#47 | T-R58 方案/判读框架与 R-03 呈现工具承接；佣金等额双边非最低档成本 +1bp/−2bp、净收益 −1bp/+2bp | 不作 r2 实跑结论；最低每边5元的1万元例增量0。冻结方案引用保持 `6814edc`，不改参数网格、runner或研究结果 |

当前 main 的 O-CI1-PROFILE-CONTRACT 优先保留：`factor_set_version` 无真实可核实集才为 null，真实集筛选为空仍保留真实版本；空态分别用 ETF `not_applicable`、无来源 `no_source`、本人证书不可用 `data_licence_unavailable`。financials、fund-flows、factors、announcements 四 GET 仅 empty/unavailable 视图，正常 owner-scoped provider/cache 尚未接入。本文不把文档目标登记当作正常数据链完成。

## Chief 裁定与源资产例外（2026-11-12）

1. **#37 跨目录注释**：除了 docs，还改 `config/market_rules.yaml` 与 `tests/backend/api_app/config_defaults/market_rules.yaml`。增量仅 `t0_round_trip.data_source` 注释，null/交易键值未变；旧测试快照两段，main 已三段。Chief 准许在当前三段 config/plan/测试快照同步注释；已只移植这9处注释，不取旧整文件，解析后的各自配置与基线完全相等，日期/税率/三段结构不变，按L0验收。
2. **#23 F23 升级依据缺口**：源 feature_spec v1.1.15、T-R62 README、f23_lexicon_spec 与冻结记录均引用“plan T-A153 F23 升级”。在当前 main、九源 PR 的 plan 及本地已取 refs 的 plan 变更记录中未找到对应升级条款；#37 的同号 T-A153 报告实际为 ETF 注释，不能互作依据。Chief 裁定当前正式 feature_spec 保 main，F23 升级暂未采纳；[源升级版原件](S1-3-history/PR-23/feature_spec.md)按原 blob 历史保全，[归档说明](S1-3-history/README.md)明确其状态。后续获派补齐有效依据后再审现行登记，不补造裁定。
3. **#23 抓取清单不完整**：源 README/stats 称两日 51 页、1530 原始条、1367 保留条；源 fetch_manifest 仅 11-02 的15页/450条，缺11-06（现存样本中997条为该日）。保留原清单与统计，不改数字凑齐、不新增抓取；该缺口交后续研究补证，不把源样本声明写成本次已验收。

上述 #23 数字按源材料保全，不宣称总体 FP≤5%；源点估计1/29=3.45%，区间上界17.18%，FN0/100上界3.70%。FP-3与K-1已知边界、非连续样本、verified_live与N-01未解除的限定均保留。A-09 的 v4 边界不自动补足 v3 升级依据。

## 本次验收与权限负例边界

- 50个新增资产与1份历史升级原件按源 blob 核等；10份 Python 仅 AST 解析，8份 YAML、4份 JSON、2份 JSONL（1467行）可解析；Markdown相对链接检查排除代码示例后无缺链（历史原件按冻结源目录解释，不改原文）。
- 当前配置/plan/测试快照解析键值一致，三段日期与税率保留；受影响的既有 `test_snapshot_equals_plan_block[market_rules]` 定点1 passed（无skip），未跑全量/coverage。
- plan/api 的 A-12、T-A157、T-A158与既有 PROFILE 版本、缺口原因及实现范围一致；静态方法/管理员隐藏/证书隔离/跨用户404/CSRF拒绝定义保留。
- 权限/路由执行文件与整合基线 blob 相同；本次没有新 HTTP/权限实现，动态权限负例由后续实现单在隔离合成环境验收。本次不冒称运行过动态权限测试。
- 文档增量 secret_scan 0阻断/0告警，gitleaks 按仓库相对路径扫描0；git diff --check通过。首次绝对路径 staging 导致现有 S7 docs 顶层豁免路径失配，原报告保全，未改扫描规则。
- GitHub CI 尚未触发；最终发布前再核最新 main 与≤3 PR CI窗口，O-BASE优先；只普通推本人 ds/，不自合、不rebase、不强推。

申请新任务：本单CI绿后交Grok审合；#23有效升级依据与缺失抓取清单归后续获派研究补证，本阶段不启动。
