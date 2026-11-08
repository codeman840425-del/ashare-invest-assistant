# P2N-08收口交接（整项未完成，不是生产验收）
最近绿色49c6c796c915fb2756910ca2625fbbb093e45605，本地未推送，工作区/索引干净。切片5交付后空闲收口，不开下一片/09。
## 本地切片链与唯一相关节点（分片计数，跨片有重复，不相加冒充总唯一数）
|切片|hash|实际边界/证据|本片节点|
|---|---|---|---|
|1|8219665d28e79a351d93f9bb311f6c6da0b6ac3c|RC5与健康纯核心；P2N-08-slice1-evidence.md|42|
|2|ba4669d4221023fcd8ee27806a711385fb652c84|RC5暂停/延期/期满事务钩子；特批两组配置；真实PG；slice2-evidence|15|
|3|a27a7ff23a154ca1f84250e19d958e0a722d0d50|实际beat→Redis→RC5期满worker→PG→既有HTTP；slice3-evidence|5|
|4|4a5f85cc95d317f52dc0e03feb981853a77d2f3b|RC6两检查核心/assessed适配、evaluation最早时点；slice4-evidence|14|
|5|49c6c796c915fb2756910ca2625fbbb093e45605|RC6实际DB部分读源→评价unknown、真实PG只读验证；slice5-evidence|3|
各片仅定向mypy/ruff/diff/暂存秘密扫描，均最终绿/扫描阻断0警告0；没有全量/coverage。失败修正过程见各片证据，未把初跑失败算通过。
## 逐项完成/未完成
|项|已实现且实际验证|尚未实现/未验收|
|---|---|---|
|RC5源|接收绑定本人/账户/实例/有效版本、哈希/PIT/政策/证据的冻结评估receipt；只合成源|实际完整平仓/本人模拟序列/真实NAV生产者；首次高值缺前值只baseline+gap，不能假造0|
|RC5核心|已平仓段含费、平本跳过，模拟按自身周期1/5/20/20、仅本人、去重，完整NAV峰值回撤；42核心中相关用例|真实资金/分钟复权/生产样本链未验|
|RC5持久化|app/feedback/pause.py：私有risk_events游标schema、实例暂停/max延期、系统审计事件、期满受阻通知同事务；实际aia_api PG、并发/回滚/重放|冻结评估快照的真实自动生产/消费触发、公开风险事件API状态机投影未接；私有游标不是公共风险事件|
|RC5事件幂等/清除|同receipt/旧观测不重复写；手动恢复不清游标；期满同检查；受阻一次通知；账户归属/手动暂停守卫|正式RC5 triggered/cleared公共事件链与真实导入重算未接|
|RC5 worker/HTTP|risk.rc5_expiry在jobs TASKS/schedule注册，间隔取现有quote_interval_s；合成真实beat/Redis/PG/本人实例HTTP、未读计数、外人404/匿名401|生产未部署/启用，实时触发worker不是本片已完成；缺日历仅保守暂停，公开gap投影待接|
|RC6源|plan_source.load实际SELECT owned计划/版本/qty/关闭审计和trades created/voided/import committed；未来边界不倒灌；真实aia_api PG验证；不读原始行/<account-field>/秘密|**没有合同定义的完整历史覆盖凭证**；coverage_at=None/complete=False，真实评价unknown；未知关闭边界不猜，不是完整读源验收|
|RC6核心|feedback/plans.py qty_over_plan/opposite_side、半开区间、仅日期歧义、同向优先/时刻/id排序、Decimal精度、冲正投影/冲突unknown；088四/089五纯案例均过|held_after_invalidation、buy_without_stop、buy_during_wait三检查真实源与核心业务接线未做|
|RC6持久化/事件幂等清除|纯投影按版本×检查返回唯一logical_key，重复同id同事实不重复，冲突拒绝|没有公共事件的DB写入/幂等/触发后清除；logical_key不等于持久化event_id|
|RC6 worker/HTTP|现有inputs→assessed→current已经真实数据库读；3节点含SQL不写/重读不变/最早证据/归属；HTTP认证路由未改|新源尚未实际HTTP+Redis worker全链验收，导入/冲正触发worker未做，未发通知|
|健康核心|权重平滑/tanh/clamp、n<20、缺日清零、观察5日/恢复10日与内部迟滞0.8、20日仅review，关闭降权只影响本人排序；纯函数已验|strategy_health_baselines/daily、user_strategy_weights实际写入/历史重放/worker/HTTP/生命周期变迁均未做。**全站版本健康**与**本人排序/RC5实例暂停**分离，不能拿本人亏损改变全局版本|
|unavailable重算|无本批完成项|T-A33到期5交易日内重算与终态冻结重算联动未落实，不得声称完成|
|evaluation.data_as_of|取实际数据/来源证据最早时点，排除settings时钟；缺时点null+gap；真实PG current源最早09:00已测|真实HTTP+全部生产维度/PIT数据源未验|
|配置|仅特批rc5_loss_streak_drawdown.sim_fail_horizon_by_horizon={intraday_t:1,short:5,swing:20,long:20}和health.internal_recover_ratio=0.8；真实文件读取/缺键gap已测|不追加其他配置/生产启用；不以缺键硬编码默认放行|
## Golden边界
084/085/087/090按切片1纯计算已验；086五日历场景/091关键计数边沿、回撤跨线、max在切片2已验但不宣称091所有生产链；092四场景切片3实际worker/HTTP合成隔离全过。
088/089切片4纯投影九例通过，切片5实际DB读证明120→冲正100、同刻归新版本、未来关闭/提交过滤；**未获得完整覆盖，不能称RC6正式判定/事件链已通过**。
## 必要外部裁定/下一入口（只记录，不启动）
1. 架构师/编排者定义完整计划+成交历史覆盖来源：覆盖起止/已捕获截至时点/账户证券作用域/提交或冲正可见性/缺口与修订语义；需持久化新schema则另行授权独立迁移，不改旧迁移。committed、余额、空/非空表、用户JSON自报均不可替代。
2. 后续可信生产者形成上述证明后，接plan_source.load→Facts/assessed，再复用已有公共risk_events状态机决定触发/清除与版本幂等；不要先把complete改true绕过。
3. RC5生产receipt入口在feedback/pause.apply_receipt，期满在feedback/worker.task与jobs risk.rc5_expiry；健康核心feedback/core.health/priority_weight；RC6核心feedback/plans.assess/select_plan。所有新状态动作仅合成隔离验收，不能代理正式G7或晋级。
4. 定点复现分别见slice1..5-evidence。当前最近片命令：PYTHONPATH=. /tmp/rv7-backend-venv/bin/pytest -q selfchecks/test_p2n08_plan_source.py（需按slice5-evidence启动专属无网络PG）；受影响适配节点selfchecks/test_p2n08_plans.py::test_existing_evaluation_adapter_bindings_disabled_and_partial_not_ok无需DB。
## 清理/权限/安全
本片PG随机DB/匿名卷/专属socket目录已精确清理；切片3 PG/Redis也已清理。本批仅遗留切片2空目录/tmp/tb70-p2n08s2-owned-pg（uid70:1000、1775），当前uid rmdir拒绝，0项、无服务/套接字；不提权，不扩大删除。
无新迁移表列/grants。真实aia_api原grants隔离验证通过；新增读源所用现有SELECT清单见slice5-evidence，未改deploy/CI/aia_maint权限，未对生产/共享库迁移。
0真实Mairui/官网/证书/私密样本/资金/正式G7/真人通知/SSE/生产调度；未创建bot routine、未推送/clone/fetch。B90b/B86挂起，B2真实采集缺口不扩。
DeepSeek：切片1–4复用reports/deepseek/P2N-08/已审纯合成操作数，安全/规则/验收本地。切片5未采用算术草稿，因不适配DB归属/审计PIT安全验证，沿用已有本地夹具；未新外调/外发源码、秘密或真实数据，不虚称本片使用。
申请新任务：已收口空闲，等待明确恢复；不自行启动新片或09。
