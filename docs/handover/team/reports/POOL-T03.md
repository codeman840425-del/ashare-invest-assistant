# POOL-T03：四个整树收集错误修复（北京时间 2026-11-11）
- 分支ds/T03，叠加ds/T02=9576a3e（PR #38）；主线基线465e020；代码冻结9491f637093007730d2315ba0f89d5491fa6b3d2（ea3cc87修复+9491f63移除多余noqa），仅本地未推送/未合入。
- 修复4项：contract/conftest在schemathesis导入前importorskip；golden在hypothesis导入前守卫；T-T61在p11_gaps导入前守卫requests；milestone显式添加本文件目录解析tt21_head。
- 仓库依赖文件未改、不增加业务依赖；缺包导致的模块skip明确披露，不作为业务通过；依赖在场时仍正常收集。
- 冻结缺包环境：1598 collected /0 collection errors，3 skipped collectors（contract、golden、T-T61），守护exit0。
- 冻结依赖在场环境：1692 collected /0 collection errors /0 skipped collectors，守护exit0；不强求旧1596总数，恢复milestone+可选模块后增长符合预期。
- 依赖在场环境：在仓库外F:/workspace/team/runtime/T03-optional临时目录安装tests/requirements.txt已有固定版本schemathesis4.33.0、hypothesis6.170.14、requests2.34.2及其依赖；未修改共享venv。
- 定点命令：python -m pytest tests/backend/golden/test_golden.py tests/backend/unit/test_tb117_session_filter_t_t61.py tests/backend/contract/test_contract_stub.py -k 'comparator or cases_directory or harness or cross_lunch or old_date or empty_session or catches_violation' -q --tb=short -p no:cacheprovider。
- 定点9 passed/6 deselected：含hypothesis真实属性测试、会话边界与坏响应契约负例；未跑live契约请求、PG/Redis fixture或全量测试体/coverage。
- 收集命令：python tests/tools/check_collection.py --output <证据路径>；两环境以PYTHONPATH是否包含上述外部目录区分；仅collect-only。
- 基线对照：T-02为1596项/4错；T-03缺包时增加2条milestone用例至1598，四个原错误全部清零。
- lint：四文件基线42条、最终41条继承诊断（去除schemathesis直接import后少一条布局诊断），按文件/规则/消息多重集比较无新增；未宣称全量ruff绿，未夹带格式清理。
- 原始日志/JSON：F:/workspace/team/status/T03-{missing-collection,present-collection}.{json,log}、T03-present-tests.log、T03-ruff-{before,after}.json。
- secret_scan改动代码与文档0阻断/0告警、git diff --check通过；无业务代码修改、无真实数据读取/麦蕊调用/共享库连接/栈变更。
- 遗留：缺依赖环境的三个模块业务测试未执行；完整测试依赖已在场环境只做收集+9项离线定点，不代替完整业务验收；专用数据库设施仍另单。
- DeepSeek：未用，导入边界和收集验收均本地完成。
申请新任务：测试池待补；r2三件套发布后按已裁定清单冻结核验。
