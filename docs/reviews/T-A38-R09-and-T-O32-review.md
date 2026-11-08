# T-A38｜R09 与 T-O32 评审

## Part 0 裁定建议（优先，可独立摘取；仅建议，不实施授权/迁移）

下表 S/I/U/D = SELECT/INSERT/UPDATE/DELETE；表名均在 app schema。五表中只有 notification_refs/intraday_candidate_refs 是新建表，其余是新增证书归属的旧表。app 指业务角色 aia_api（含 worker），不等于数据库属主。

| 表 | aia_ingest 最小 S/I/U/D | app/aia_api 业务对照 | aia_maint 对照 | 代码证据 |
|---|---|---|---|---|
| notification_refs | 全无，撤回 SIUD | S、I；无 U/D | S(notification_id)、D；无 I/U | notify/service.py:20–28,119–124；cli/delete_user_data.py:182–185 |
| intraday_candidate_refs | 全无，撤回 SIUD | S、I；无 U/D | S(instance_id)、D；无 I/U | intraday/engine.py:501–506,575–578；cli/delete_user_data.py:241–244 |
| signal_states | 全无，撤回 SIUD | S、I、U(last_tick_id,rule_states,state,changed_at)；无 D | S(source_licence_id)、D；无 I/U | intraday/engine.py:307–334,360–374；cli/delete_user_data.py:255–258 |
| intraday_universe | 全无，撤回 SIUD | I、U(computed_at)，S 仅限 UPSERT 所需列；无 D | S(source_licence_id)、D；无 I/U | intraday/engine.py:138–151；cli/delete_user_data.py:259–262 |
| signal_events | 全无，撤回 SIUD | S、I；无 U/D | S(id,user_id,source_licence_id)、D；无 I/U，仍受归属触发器保护 | intraday/engine.py:432–447,463–464,698–706；intraday/events.py:20–31；cli/delete_user_data.py:263–267 |

上表代码路径均相对 `src/backend/app/`；app 的列级精确授权须在隔离库用实际语句验证（特别是 UPSERT 的 SELECT 依赖），不得为了测试方便扩大到属主。当前通知/事件投影多用 select(table)，其 S 是全投影字段；并非假设所有表都能仅授谓词列。维护角色的关联子查询还依赖现有 notifications/strategy_instances/user_data_licences 的点名 SELECT，不能只授本表即宣称全链通过。

**ingest 无访问需求的依据**：`workers/ingest.py:86–105,123–124` 唯一业务入口是 `ingest.daily_lists.tick`；后者 `:367–382` 消费日列表、调用 process 并将 APPLY 投递给 worker，不在 ingest 执行 P2N-06 语句。`daily_lists.py:192–198,221–228,261–284,314–328` 实际访问批次/列表行/master_runs/securities；搜索 ingest 包及入口未见五表引用。`workers/runner.py:30–35,49–57` 只做启动版本检查并调用传入 tick，不能把 worker/独立 signal-rt 的权限算给 ingest。启动读 alembic_version 与其他既有 ingest 授权不受本建议影响。

**实施建议与责任**：运维按 T-A30 的“先宽授、末尾定点收回并自检”模式，对五表撤清 aia_ingest 的表级与遗留列级 SIUD（同时维持无 DDL/TRUNCATE/REFERENCES/TRIGGER），检查角色成员继承及 PUBLIC，防止 broad/default privileges 下次 apply 又恢复。迁移后再 apply-roles；缺表时不得自动补造，部署阶段应失败/明确未迁移。正向测既有 ingest 日列表链，负向测五表每项 SIUD 都拒绝；不以“代码当前不调用”替代有效 ACL 验证。无需给 ingest 新权限。

**与 T-A35 I1 的关系**：main 的 grants 缺维护权限；运维 `c2353bf` 已在 ops/T-O32-trial 的 grants.sql:313–320,353–354 补齐表中维护列/DELETE，并据 T-O32 报告验证，但尚不是 main 的修复。它不更新数据库中的 purge_row_owner：`0013_t_b16_core_r2.py:42–55,262–299` 仍按 signal_events.user_id 取归属；scope=shared 新事件 user_id 可空，故补 ACL 不等于修复共享事件删除保护。后端须追加归属函数迁移，先用 source_licence_id→user_data_licences.user_id 确定本人；user 层同时验证 user_id 一致，冲突拒绝，禁止撤触发器或改用属主删。

### 旧 signal_events 的确定性迁移/回填建议

| 对象 | 可回填的充分证据与规则 | 不可证明时及回滚约束 | 归属 |
|---|---|---|---|
| 来源证书/事件正文 | 仅原始不可变快照、明确原始外键或已核对导入映射能唯一证明 licence、用户、证券、时点、版本/params 时回填；保留事件 id、正文、时间、hash 与映射审计 | user_id 或当前唯一证书不足以证明历史来源；无证据继续拒迁，不猜归属、不清表；另行批准隔离 legacy 存档后才可改方案 | 后端 T-B92；架构确认隔离方案 |
| instance_id/instance_ids/候选 | 只按事件当时可证明的历史绑定与已存在候选关系，按 T-A34 created_at,id 排序、优先已产候选者，冻结结果；不重跑规则生成历史候选 | 不用当前实例状态冒充历史；缺历史绑定是 unknown，不把 null/[]冒充“已证实集合为空”，该事件不进入新可见投影 | 后端 T-B92 |
| 通知 refs/回滚 | 仅显式历史 notification→event/condition 关系可建唯一 refs；旧无关系通知保持旧投影 refs=[]；不凭证券+时间近似关联，不补通知、不重置已读、不虚增 merged_count/version | 保存原 schema 数据与新增映射的可逆清单；先验证旧唯一键/外键冲突，失败整批回滚；0026子表降级前保留完整refs，升级恢复；0025不得固定抛错冒充可回滚 | 后端 T-B92；运维隔离升降级验证 |

这是保守的建议门槛，不授权删除旧事实或推生产。可选“新增 legacy 隔离存档/允许旧记录归属 nullable 且新写强制非空”的具体 schema 属需另审方案，当前默认维持非空旧事件拒迁。旧事件拒迁是 fail-closed 升级边界；T-A35 B1 原问题是 downgrade 不可执行，二者不能混为同一故障。T-O32.md:7–10 已验证非空 user/shared 两事件拒迁、库保持0023；不能据此宣称非空升级成功。state/universe 可重建亦应留前后计数/清理记录，迁移验证与实际业务进程禁用状态分开。

## 范围与方法
- Part 1：只评审研究员提交 `d976d3630049a4227740e88cddb1c91ac736083f` 的三文件，不修改/提交 docs/strategies。案例行号按该提交，checker 行号未变。检查中研究员开始修改 R09 工作树，因此最终两次验证用 git show 的已提交源码/JSON在内存执行，源文档仍只读，避免把WIP当交付。
- Part 2：本地 main 截止 `fd2e707825aa490751a0916772f46f089143ae47`；origin/main=`34c88c3`，其后42个本地未推送提交。只读本地引用，不 fetch、不克隆、不合并、不 push。
- Part 0补充读取 T-O32.md（北京时间17:15更新）及 ops 分支 `c2353bf`，不把该分支提交误称已在 main，也不把未提交 T-B91/WIP 当候选。

## Part 1｜P2N-R09
**结论：固定输入下确定性通过；按 T-A36 仍需修订 oracle。阻断0、重要2、建议0。**

### R1 重要｜数字守卫尚非 T-A36 精度/换算口径（研究员）
- 位置：`docs/strategies/golden/check_P2N-R09.py:6,16,20,75–90`；README:41。
- 当前 Decimal 只做原值等号比较，没有 quantize/ROUND_HALF_UP；12.345→12.35 的合法两位舍入会报 unsupported_number；12.40→12.4 数值相等而少一位仍通过；万元被识别但仅按原数值/单位匹配，亿元未完整识别，合法精确换算不能正确接受。
- 实测内存突变首个 accepted 文本12.40→12.4，findings(include_review=False)=[]；完整审阅哈希会拦改文案，因此这不是声称既有19条已误判，而是独立数字守卫/覆盖未实现新裁定。
- 应按引用证据值，先检查单位及仅万/亿允许换算，再以显示d位 Decimal ROUND_HALF_UP 比较；百分数/价格 d≥min(证据小数位,2)，不是无条件所有数字至少2位；计数精确相等。约/近/超过不放宽。补正负半舍、尾零、百分数、计数、万/亿与不允许换算的正负例，不用float。

### R2 重要｜065–067 已有裁定，不应继续 blocked（研究员）
- 位置：`P2N-R09_golden.json`（d976d36）:19313（065）、19590（066）、19867（067）；checker:134–137；README:5–6,31,50–58。
- 三条均改 ready，且本例原文均应 **rejected**：065 引用12.40元/股，却写“约为12元/股”，d=0<2，即使HALF_UP至整数等于12仍精度不合格；066“系统原判定文字为减仓”命中动作词，无事实转述白名单；067“不保证收益”含禁词“保证”，否定/免责无例外。
- 更新 expected.findings/semantic_review/audit/source_registry 至 T-A36；候选未变则现有candidate hash不必伪改，审阅结论必须重新确认。可沿既有测试标签记录 numeric_precision/action_word/prohibited_term，不能造生产 reject_reason。
- 回退投影 source=template、validation_status=fallback、fallback_reason=validation_failed，规则字段保持不变；固定免责仍由系统在LLM正文外追加。更新README、统计及mutation覆盖，不只改expected让脚本自证。
- 若其余64例保持不变，目标计数为19 accepted、48 rejected、0 blocked；有限审阅oracle不等于通用中文语义分类器，后端守卫需独立实现。研究员正在处理的未提交WIP不计作本次交付或已修。

### Part 1 已核对
- 标准命令连续两次均rc0、stdout/stderr逐字一致；排除WIP后，用d976d36的checker/JSON内存快照再次两次均rc0且输出一致：19 accepted/45 rejected/3 blocked；5项结构突变检测、6项审阅hash复用拦截。
- 无random/time/network/model调用、无业务导入；findings排序，输入/输出遍历稳定，Counter按固定案例顺序输出；JSON中float值数量0。依赖当前引用文档短引存在，复现需固定包及文档版本，不能以哈希说明泛化正确。
- 对引用存在、已启用策略/规则passed、六维并列、保护action/score/confidence/stops、不可变快照、固定免责与PII外发前阻断有有限oracle覆盖，符合P1a/plan防幻觉方向。语义依赖明确标注的人工审阅标签，不误称模型二次裁决。
- 证券代码仅999001.SZ/999002.SZ虚构占位，名称/行业/账户快照UUID为合成；故意PII输入例064也是synthetic，不是真实账户/用户名。未发现真实证券/账户/凭据值；不重复外发任何夹具。

## Part 2｜T-O32 试合清单
**结论：历史试合祖先/迁移顺序合理，但清单不足以作为当前收口批准依据，需同步。阻断0、重要3、建议0。**

### O1 重要｜两清单状态矛盾，main后续11提交未逐项登记（运维，编排者确认候选资格）
- 位置：`/workspace/team/artifacts/T-O32-manifest.md:4–9`；`/workspace/team/reports/T-O32-merge-candidates.md:5,10,18–21`。
- manifest已合6d096cd/fb6f971/9b5ab11，而merge-candidates仍称未合、待确认；05b在前者明确已含59261c1，后者仍待核hash。实测59261c1是96a4b68祖先，无需重合，也不是缺失实现。
- 相对manifest固定试合4ccc859，当前main快照缺入试合的11提交按顺序为：462057c、f811992、93df55a、0c20834、d976d36、25efe5a、78cd872、3b36b74、37f8d65、6c419b1、fd2e707。462057c曾显式排除，不算偷漏，但必须更新当前待审/排除理由；其余也应逐项登记纳入/待验/排除，不能自动等同已验收。
- 正确做法：固定origin/main与main快照，列42提交的祖先覆盖和上述增量，保留依赖顺序，修正相互矛盾的状态；由编排者确认资格，不因“本地已提交”自动试合/推送。

### O2 重要｜实际ops试合分支已前进，最终hash/材料仍指旧快照（运维）
- 位置：manifest:2,11–15；T-O32.md:2–3；提交 `c2353bf`。
- manifest称最终基线4ccc859，而当前ops/T-O32-trial=c2353bf（父4ccc859），新增8个deploy文件；T-O32.md已明确此交付。c2353bf不在main，不能混进42个main增量，也不能继续用旧delta/旧扫描摘要代表新交付树。
- 应区分“历史试合快照4ccc859”与“当前ops交付c2353bf”，为新提交登记精确hash、文件范围、验收状态及独立材料/校验和；若manifest刻意冻结，增加清楚的后续增量索引而非覆盖旧证据。报告自承9b5ab11角色误标ops，应改为前端（05h）。
- 未发现历史合并顺序错误：9cd2672父96a4b68+d0a6644，03df03b父9cd2672+f078582，b7e5aeb父03df03b+9b5ab11，4ccc859父b7e5aeb+be685b1；测试分支39提交仅tests，运维分支增量为7个deploy/CI文件，属于清单点名侧枝，不因不在main就当多余。

### O3 重要｜待修门槛未入原清单，旧事件升级提示须区分拒迁（运维登记，后端修复）
- 位置：manifest:9–10,17–18；merge-candidates:18–21；补充T-O32.md:7–10,17–20。
- 原两清单未标P2N-06 B1 downgrade阻断、T-B91/T-B92/T-O33未交付/待修；manifest仅说“旧事件计数保持”，不能作为非空旧事件升级成功的断言。最新T-O32.md补充证明：空事件0=0可升；非空user/shared两例被0025拒绝且库停0023，不丢数据，并非已迁移。
- 应在候选登记单列：B1回滚待T-B92；旧事件迁移/回填待Part0建议获确认；T-B91修复尚未纳入本main快照；T-B92多实例/共享归属待验；T-O33依赖未交付，禁以试合无冲突替代ACL/生产验收。新角色收窄建议也在Part0，尚未执行。当前WIP绝不登记hash或视为候选。
- 非空旧事件未有可信映射前，应预演“升级明确失败、事务回滚、旧计数不变”；若未来实现映射，再新增成功升级与可逆回退用例，不删除旧事件凑0。DB迁移先head再db-roles，不能在0023上跑需0024列的授权脚本并认为迁移坏了。

### Part 2 迁移静态核对
- `src/backend/migrations/versions` AST核验：唯一head=0026，无缺失父revision，无分叉；末段0020→0022→0023→0024→0025→0026。0021不在活动链，0022.down_revision=0020；编号跳过不等于断链，不能为了“补序号”合入paused0021。
- 0024顺接0023；0025顺接0024；0026顺接0025。依赖顺序正确不代表downgrade通过，0025固定抛错的T-A35 B1仍然存在。本次不跑数据库、不启动服务、不复跑运维容器验证。

## 交付与验证边界
- 只提交本评审文档；未修改/提交策略目录、运维清单、任何代码或他人暂存；没有push、全量测试、coverage、真实麦蕊/模型/官网调用。
- 提交前本文件files模式secret_scan要求阻断0，随后git diff --check -- docs；单路径本地提交。

DeepSeek：未用，原因 评审结论、权限与迁移安全裁定禁止外包。
申请新任务：运维确认Part0最小ACL，后端落实旧事件/回滚方案，研究员完成R09新裁定后分别定点复审。
