# P2N-08 切片4证据：RC6两检查核心/评价适配（不是worker闭环）
本地提交4a5f85cc95d317f52dc0e03feb981853a77d2f3b；依据当前api-contract§7.11.3 T-A33第6–7点、plan P2N-08与golden088/089；T-A36/37未扩RC6规则。
## 实现及最小范围
- app/feedback/plans.py：显式带owner/account/code的Plan/Trade/Facts数据结构，选择半开有效版本，Decimal累计同向数量并严格>计划量才告警；逻辑key按版本×检查去重，不接受预期答案/固定golden标识。
- 所有原始事实由后续可信数据库生产者提供；coverage_complete且水位绑定本次as_of才允许评价，不拿未证明完整的空列表当无违规。未知结束可见来源/计划量、日期精度版本变更、重复id冲突均保守gap。未来事实不回填历史，future end_known_at不追溯改变此前区间。
- 同向版本优先，随后按生效时刻最新、并列id最小；无同向才判opposite_side。仅日期按15:00，已知同日版本边界不分配、不出flag。
- 撤销事实不累计，包括撤销原行的负数量；原活动/撤销版本同时存在但缺明确投影的同id冲突，不擅自择一。完整有效投影可独立重算冲正后的数量/告警。
- 每版本×检查只返回一个logical_key，重复同id相同事实幂等；该key尚非数据库事件id，未声称公共RiskEvent的新增/清除/幂等已接通。
- app/risk/evaluation.py Inputs新增可选RC6事实及可信owner/code绑定，工厂填owner/code；assessed仅绑定一致才投影两检查，禁用不告警，不改变动作/分数/数量门控或RC5暂停；其余held_after_invalidation/buy_without_stop/buy_during_wait保留具体gap。
- 未增加HTTP客户端可传Facts的入口，现有数据库inputs没有RC6生产加载器，所以真实GET仍unknown，不全局把business_facts_not_connected翻成ok。
- current评价data_as_of改取上下文和实际证据最早值，排除settings当前时钟；必要时点缺失则null+gap，不用max伪装新鲜。GET调用链未增加execute写语句；本片仅OpenAPI GET契约测试，未宣称实际PG HTTP写计数验证。
## 14唯一定点
新增模块13节点：088四案例全部直接运算，089五案例全部直接选择；作用域/PIT/缺证/重复/冲正1，精确Decimal/日期与版本可见性1，实际assessed适配/禁用/三检查缺源1，最早时点/缺时间1。
既有test_p2n02_risk_controls.py::test_contract_output_routes_default_schema_and_readonly_evaluation一节点验证GET-only现有接口/形状，合计14；无RC5/092或42核心重跑。
初跑 /tmp/p2n08-s4-plans.log：12过1失败，仅测试直接赋值冻结Config；改为model_copy后 /tmp/p2n08-s4-adapter.log 1过。不是产品放宽配置。
补撤销负原行后仅复验作用域节点+既有GET契约，/tmp/p2n08-s4-scope-contract.log 2过。上述重复节点不累计；唯一14均最终通过。
命令（cwd=src/backend，PYTHONPATH=.）：/tmp/rv7-backend-venv/bin/pytest -q selfchecks/test_p2n08_plans.py；修改后只运行对应节点，以及 selfchecks/test_p2n02_risk_controls.py::test_contract_output_routes_default_schema_and_readonly_evaluation。
/tmp/rv7-backend-venv/bin/mypy --follow-imports=silent app/feedback/plans.py app/risk/evaluation.py通过；只3变动路径ruff/diff通过；secret_scan staged扫描3路径，阻断0/警告0；无全量/coverage。
## 未验收与资源
本片不含数据库读源/生产计划历史投影、真实API/PG/Redis RC6闭环、导入冲正/版本变更触发worker、公共风险事件状态机的幂等与清除、其余三检查；下一片应从这些既有表/事实的确定性读取接入，不从本核心成功推断生产可用。
没有创建PG/Redis或其他服务，不需清理容器；旧切片2 uid70空目录仍原样保留，未提权。无真实Mairui/官网/证书/私密/资金/G7/调度/提醒。
健康历史持久化、RC5生产评估源、unavailable重算等仍TODO。B90b/B86保持挂起，B2真实采集缺口不扩展。
DeepSeek：复用reports/deepseek/P2N-08/已审24纯合成操作数中两项作重复输入次数，逐条复核，未新发任何源码/秘密/真实响应；业务规则/裁定/预期与验收本地。
