# P2N-R09 六维证据 → 中文解释金标准 v1

## 交付与消费方式

- **67例：64 ready（19 accepted、45 rejected）+3 blocked/spec_ambiguity**。全部纯虚构，股票标签999001.SZ/999002.SZ、名称及行业都是合成占位，不代表真实证券/账户/行情。只新增本包，不修改R08或执行排队的R08b。
- 只取`case_status == "ready"`。每例独立内含input证据包、candidate中文模型JSON、paragraph_bindings、逐步audit_steps、expected、精确来源条款和semantic_review。blocked.expected=null不代表接受或业务null，必须显式skip/xfail并列明问题。
- candidate沿plan §2.7的模型输出`{paragraphs:[{text,cites}]}`；接受后按契约 §7.11.4/§5.1转为`TextWithEvidence{text,expr:null,evidence_ids}`，text按段换行拼接。**不是完整HTTP响应**：expected.explanation_projection只断言既有字段；protected_result是action/score/confidence/stops的不变投影。
- verdict、findings、paragraph_bindings、semantic_review、scope等都是**测试夹具元数据**，不增加任何生产API字段/拒绝枚举。契约没有定义此处的reject_reason，故本包不造reject_reason，也不把fixture finding写作HTTP错误码。rejected表示候选不可采用/故障无候选，落既有source=template、validation_status=fallback，不表示整份建议请求报错。
- budget/PII未调用模型的回退例明确llm_call_id=null；其他失败不猜实际记录ID。模板正文、真实LLM调用UUID/供应商运行状态不由本包伪造。接受候选也不生成计划草案。

## 权威范围

依据plan-phase2-next P2N-09、plan §0A.4/§2.7/§2.7.2、api-contract §5.1/§7.11.4、phase2_daily_dimensions、H-01/W-01 v2与当前固定disclaimer。source_registry逐条给file/section/原文短引；自核确认短引仍存在。本轮窄读刷新，不重读大文件或重跑旧检查。

启用卡限定为输入明确启用的H-01/W-01 v2合成simulating快照；不把其当已获生产G7，不扩展策略清单。H-01纯离场score=null，不伪造buy/add；规则快照已有的W1/I1/C1及W-01 C3仅解释，不重算规则或覆盖动作。六维事实不等于六个交易结论；RSI等事实归属与原卡规则归属不相互覆盖。

证据统一provider=system、epistemic_type=hypothesis，并为每段加“模拟回放”标识；不是mairui实测。announcement.zt是公告记录字段的测试key，不注册新f.*键；行业为合成标签，不验证真实申万编码。未知F21的value/unit/known_at仍null，等级declared不晋级；新闻标题展示不等于F23验收。无需/不会从R08尚待处理的规则推导解释真值。

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
| 待明确 | 065–067 | 不计通过，见下表 |

编号为本包P2N-R09-前缀。文本里只解释原事实/原判定，未输出新动作；候选信号不是收益承诺。合格完整六维包与H/W分歧包为不同scope，不强制单句解释也写六维。

## 自核方法与边界

执行`python3 docs/strategies/golden/check_P2N-R09.py`。只读本包及所引文档，零业务导入/零模型二次裁决/零网络/零旧检查。64例oracle核对PASS，3例明确未运行。

确定性部分直接检查候选原文/结构，而非读取expected标签作判断：
1. 每句存在内联引用，引用集与cites一致；本对象证据ID唯一且可解析；不借另一快照的ID。
2. 数字只从**该段所引证据**授权，使用Decimal核原值；单位精确匹配，不把pct/ratio或元/万元相混。未约定舍入不默许换数。股票代码与虚构主体白名单检查。
3. paragraph_bindings用于有限测试中的事实/维度/策略/RuleRef绑定；明确启用的策略、passed与已有快照一致。模型额外改protected字段或不符合paragraphs schema即拒绝。
4. 六维完整scope各恰一项；策略分歧scope两卡分别保留；未设任何“综合结论”字段。固定免责从当前compliance原文加载，旧已停用问卷/同意门禁不恢复。
5. 接受后的cites→evidence_ids、text换行拼接、source/validation_status回退及protected_result逐字段不变。

**语义部分不是关键词万能分类器**：每例semantic_review包含逐句审阅说明、具体问题及候选JSON SHA256；承诺/未知填充/观点混并/实测冒充等语义由研究员按条款人工式核对。绑定哈希防止新文本复用旧审阅，不能证明一般自由中文都合规，也不是后端应照抄的生产安全守卫。受审文本外的新候选必须重新审阅/由实现守卫处理。

篡改证明：从accepted例出发，独立改数字、引用、单位、新主体、action，**5项均被确定性守卫抓到**；全部无法复用原审阅哈希。另加一项有引用且不添数字的收益承诺：结构守卫刻意不声称能识别其语义，但哈希要求重新审阅，共**6项审阅复用被阻断**。因此PASS只是这64个既定oracle的有限核验，不是任意中文通用鉴定，也不证明后端联调或生产门禁通过。

## 未决文本细节（不混入通过）

| ID | 问题 |
|---|---|
| P2N-R09-065 | 计划允许按约定四舍五入，但本输入没有约定；数值展示精度/约字容差如何配置需明确。 |
| P2N-R09-066 | 规则动作可见与LLM不允许动作词之间，事实性转述动作是否有白名单？未裁定不自行放行。 |
| P2N-R09-067 | 禁用词在否定式免责声明/引用中是否存在明确例外？不靠词命中判定所有中文语义。 |

这些只影响具体文本边界，不阻断其他64例消费；本包不对动作转述或否定禁词自行添加豁免。若需要扩展，应先明确规则再加定点案例，不二次调用模型裁决。

## DeepSeek与交付

DeepSeek：用于24条六维纯虚构事实中文改写及故意新增数字/错引的机械草稿（产出目录reports/deepseek/P2N-R09/，实际在team目录）。一次deepseek-flash官方认证调用成功，2026-11-08 17:00:15北京时间开始，4.089秒，1252 tokens；无重试。只发送虚构schema/事实与文字种子，无真实持仓/账户、私有文档或团队原文/密钥/原始响应，未让模型给接受或合规标签。

模型draft.json保持原样“未核实”留档；本地逐行复核24条，加模拟回放前缀并绑定真实规格引用；标签、扩展负例、条件绑定、三项歧义由研究员独立裁定。review.json关联draft_seed_id，最终逐例审阅留在本包semantic_review。本包采用本角色按三文件精确白名单扫描、仅本地提交的交付流程，不请求其他团队成员代交，不推送；共享暂存区他人文件不操作。R08b作为后续独立任务另行处理。

提交扫描处理记录：首次gitleaks在028例的合成证据key产生1项generic-api-key命中。逐项对照本轮build_reviewed.py确认由研究员为null公告计数用例写入，不是任何凭证。仅将该key改为短测试标签news_gap，并在该例fixture_feature_refs保留正式特征映射；消费者适配时可据此解析，未知数值/单位和引用ID不变。未增加豁免、改忽略项/规则/基线或关闭hook；首次失败记录保留。
