# P2N-R09 六维证据 → 中文解释金标准 v1 / T-A36增量

## 交付与消费方式

- **67 ready（19 accepted、48 rejected），0 blocked**：原64例内容不变，065–067依T-A36均裁为rejected。全部纯虚构，股票标签999001.SZ/999002.SZ、名称及行业都是合成占位，不代表真实证券/账户/行情。本次仅本包三文件增量，不修改或重跑R08/R08b。
- 只取`case_status == "ready"`。每例独立内含input证据包、candidate中文模型JSON、paragraph_bindings、逐步audit_steps、expected、精确来源条款和semantic_review。blocked.expected=null不代表接受或业务null，必须显式skip/xfail并列明问题。
- candidate沿plan §2.7的模型输出`{paragraphs:[{text,cites}]}`；接受后按契约 §7.11.4/§5.1转为`TextWithEvidence{text,expr:null,evidence_ids}`，text按段换行拼接。**不是完整HTTP响应**：expected.explanation_projection只断言既有字段；protected_result是action/score/confidence/stops的不变投影。
- verdict、findings、paragraph_bindings、semantic_review、scope等都是**测试夹具元数据**，不增加任何生产API字段/拒绝枚举。契约没有定义此处的reject_reason，故本包不造reject_reason，也不把fixture finding写作HTTP错误码。rejected表示候选不可采用/故障无候选，落既有source=template、validation_status=fallback，不表示整份建议请求报错。
- budget/PII未调用模型的回退例明确llm_call_id=null；其他失败不猜实际记录ID。模板正文、真实LLM调用UUID/供应商运行状态不由本包伪造。接受候选也不生成计划草案。

## 权威范围

依据plan-phase2-next P2N-09、plan §0A.4/§2.7/§2.7.2、api-contract §5.1/§7.11.4、phase2_daily_dimensions、H-01/W-01 v2与当前固定disclaimer。source_registry逐条给file/section/原文短引；自核确认短引仍存在。本轮窄读刷新，不重读大文件或重跑旧检查。

启用卡限定为输入明确启用的H-01/W-01 v2合成simulating快照；不把其当已获生产G7，不扩展策略清单。H-01纯离场score=null，不伪造buy/add；规则快照已有的W1/I1/C1及W-01 C3仅解释，不重算规则或覆盖动作。六维事实不等于六个交易结论；RSI等事实归属与原卡规则归属不相互覆盖。

证据统一provider=system、epistemic_type=hypothesis，并为每段加“模拟回放”标识；不是mairui实测。announcement.zt是公告记录字段的测试key，不注册新f.*键；行业为合成标签，不验证真实申万编码。未知F21的value/unit/known_at仍null，等级declared不晋级；新闻标题展示不等于F23验收。不从其他任务规则推导本包解释真值。

## 覆盖矩阵

| 范围 | 案例/数量 | 断言 |
|---|---|---|
| 六维逐维改写 | 001–024，各维4例 | 原值/单位两种中文转述；新增17%及错引其他维度分别拒绝 |
| 六维完整 | 025–026、050 | 六维各一段；缺维却声称完整、合成总观点拒绝 |
| 未知保留 | 027–028、047–049 | null不当0；单位/PIT未知不补；declared不升实盘核实 |
| 引用/原值/主体 | 029–035、054 | 每句引用、cites与内联一致、ID本对象存在；错引同值不同单位/新主体/跨快照拒绝 |
| 合规/规则不变 | 036–041、055–057 | 动作/收益承诺、禁用措辞、action/score/confidence/stops变更、假设冒充实测、改免责及改已提交正文拒绝 |
| 条件/反证/失效 | 042–046 | 已判条件true/false分别绑定RuleRef；反证不抵消主判定；改命中/补阈值拒绝 |
| 策略分歧 | 051–053 | H/W各自保留原判定；合并/取主策略/未启用卡拒绝 |
| 故障及输入守卫 | 058–064 | 纯合成timeout/401/402/429/预算/模型失败终态回退；PII外发前阻断；原规则字段不变 |
| T-A36三项闭合 | 065–067 | 三项均拒绝：数字位数不足、动作事实转述、否定禁用词；见下表 |

编号为本包P2N-R09-前缀。文本里只解释原事实/原判定，未输出新动作；候选信号不是收益承诺。合格完整六维包与H/W分歧包为不同scope，不强制单句解释也写六维。

## 自核方法与边界

本增量执行`python3 docs/strategies/golden/check_P2N-R09.py --r09b`，只运行065–067及其13项数字算子探针、篡改测试。原64例逐例与d976d3630049a4227740e88cddb1c91ac736083f比较完全相同，沿用其历史PASS，不重跑其oracle；无参数为整包入口，本轮未跑。零业务导入/零模型二次裁决/零网络/零全量。

确定性部分直接检查候选原文/结构，而非读取expected标签作判断：
1. 每句存在内联引用，引用集与cites一致；本对象证据ID唯一且可解析；不借另一快照的ID。
2. 数字只从**该段所引证据**授权，使用Decimal核原值；单位精确匹配，不把pct/ratio或元/万元相混。原64例原值比较保持；新增三例依T-A36第4点作ROUND_HALF_UP及最小位数/计数精确/万亿换算，不创设约字容差或新配置。股票代码与虚构主体白名单检查。
3. paragraph_bindings用于有限测试中的事实/维度/策略/RuleRef绑定；明确启用的策略、passed与已有快照一致。模型额外改protected字段或不符合paragraphs schema即拒绝。
4. 六维完整scope各恰一项；策略分歧scope两卡分别保留；未设任何“综合结论”字段。固定免责从当前compliance原文加载，旧已停用问卷/同意门禁不恢复。
5. 接受后的cites→evidence_ids、text换行拼接、source/validation_status回退及protected_result逐字段不变。

**语义部分不是关键词万能分类器**：每例semantic_review包含逐句审阅说明、具体问题及候选JSON SHA256；承诺/未知填充/观点混并/实测冒充等语义由研究员按条款人工式核对。绑定哈希防止新文本复用旧审阅，不能证明一般自由中文都合规，也不是后端应照抄的生产安全守卫。受审文本外的新候选必须重新审阅/由实现守卫处理。

篡改证明：从accepted例出发，独立改数字、引用、单位、新主体、action，**5项均被确定性守卫抓到**；全部无法复用原审阅哈希。另加一项有引用且不添数字的收益承诺：结构守卫刻意不声称能识别其语义，但哈希要求重新审阅，共**6项审阅复用被阻断**。上述为原64例历史篡改记录，本增量不重跑。因此原PASS只是这64个既定oracle的有限核验，不是任意中文通用鉴定，也不证明后端联调或生产门禁通过。

## T-A36三项正式裁定（内部追踪P2N-R09b，非新编排任务号）

依据78cd872及当前api-contract §7.11.4第2/4–6点；原候选文本保留，三项现均ready/rejected，不再blocked。

| ID | 输入/逐句审阅与精确期望 |
|---|---|
| 065 | E_T=12.40元/股，候选“约为12元/股”：d=0、证据小数位p=2；ROUND_HALF_UP(12.40,0)=12虽相等，但0<min(2,2)=2；约字不放宽，findings=numeric_precision。配置仅用正式explain_guard.min_decimals默认2。 |
| 066 | “系统原判定文字为减仓”确为protected_result.action=reduce转述；T-A36规定任何动作词均拒绝，无白名单，findings=action_word。规则动作仅由界面从规则字段展示。 |
| 067 | “本工具不保证收益”出现禁用词“保证”，即使是否定句亦无例外，findings=prohibited_term。固定免责由系统在LLM之外追加，LLM不得自写。 |

三例的explanation_projection均为source=template、validation_status=fallback、fallback_reason=validation_failed；不是完整HTTP体，不猜调用UUID或模板正文；protected_result逐字段不变。findings仍为夹具字段，不新增reject_reason。原64例的投影保持原有窄范围，不冒充完整当前Explanation体。

065附13个数字算子探针：12.345→12.35半入/12.34拒绝、价格/百分数最低位数、整数百分数、计数精确、8000元→0.80万元、123500000元→1.24亿元、千元及单位错配拒绝。全部由独立Decimal输入函数重算，不读取expected产生计算结果；numeric_calculation也逐字段重算复核。探针不是13个完整新解释案例。

三例semantic_review逐句列条款、候选和原因，并绑定候选text_sha256及candidate/input/paragraph_bindings组合hash。新增机械守卫仅对这三例适用，不改变原64例检查语义；动作/禁词机械断言只覆盖本次实见“减仓”“保证”，不是完整词库，更不是未命中就放行的白名单。三个文本改写使机械命中消失，但旧审阅hash均失效；一个证据篡改也必须重审。清空三个审阅标签仍无法消除机械拒绝；三个伪造accepted标签也均被拒绝。**机械通过不代表新文本语义合格**，生产任意中文的合规能力不由本包证明。

## DeepSeek与交付

DeepSeek：用于24条六维纯虚构事实中文改写及故意新增数字/错引的机械草稿（产出目录reports/deepseek/P2N-R09/，实际在team目录）。一次deepseek-flash官方认证调用成功，2026-11-08 17:00:15北京时间开始，4.089秒，1252 tokens；无重试。只发送虚构schema/事实与文字种子，无真实持仓/账户、私有文档或团队原文/密钥/原始响应，未让模型给接受或合规标签。

模型draft.json保持原样“未核实”留档；本地逐行复核24条，加模拟回放前缀并绑定真实规格引用；标签、扩展负例、条件绑定、三项歧义由研究员独立裁定。review.json关联draft_seed_id，最终逐例审阅留在本包semantic_review。本包采用本角色按三文件精确白名单扫描、仅本地提交的交付流程，不请求其他团队成员代交，不推送；共享暂存区他人文件不操作。其他任务独立处理，不在本轮启动。

提交扫描处理记录：首次gitleaks在028例的合成证据key产生1项generic-api-key命中。逐项对照本轮build_reviewed.py确认由研究员为null公告计数用例写入，不是任何凭证。仅将该key改为短测试标签news_gap，并在该例fixture_feature_refs保留正式特征映射；消费者适配时可据此解析，未知数值/单位和引用ID不变。未增加豁免、改忽略项/规则/基线或关闭hook；首次失败记录保留。

DeepSeek增量：复用reports/deepseek/P2N-R09/已有虚构文字草稿；本轮无新调用、0tokens，增量复核记录reports/deepseek/P2N-R09b/review.json。原历史1次1252tokens不重复计为本轮调用。本角色对三精确路径扫描及本地提交，不推送。
