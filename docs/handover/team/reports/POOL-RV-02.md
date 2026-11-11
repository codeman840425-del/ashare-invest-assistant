# POOL-RV-02：测试独立抽查三PR门禁（北京时间2026-11-11）
- 报告分支ds/RV02，基线465e020；仅本地未推送/未合入。冻结远端PR #11=7787441e635818790d380945e216ff2a2f150668、#15=41c58e40994c0cb62a6a372d032a29e1b845f1e3、#26=9beee6eb4d40cafbea7309195f0307336f755039。
- 三份源码各放.worktrees/RV02-pr{11,15,26} detached目录；未修改远端/原执行树，不合并、不写库、不调麦蕊。
- #11命令：python -m pytest tests/backend/api_app/test_config_yaml_defaults.py -q --tb=short -p no:cacheprovider → 59 passed/3 xfailed/**1 failed**；失败为BUSINESS_FILES额外share_class_list（PR已披露既有问题）。
- #11 PR所称59过/3xfail数字可复现，但省略失败易误读；380项整api_app回归未复跑，不能确认该声明。
- #11负控：快照首段stamp_duty_sell_pct 0.05→0.06，snapshot_equals_plan_block[market_rules] FAIL/exit1，repo_yaml_equals_plan_defaults[market_rules] XFAIL/exit0。
- #11负控：仓库config首段同值0.05→0.07，snapshot_equals_plan_block[market_rules] **PASS/exit0**，repo_yaml_equals_plan_defaults[market_rules] **XFAIL/exit0**；与PR“坏仓库配置同样FAILED/严格比对生效”声明不一致，需澄清或并入后续严格门禁修复，不能原样按门禁全过放行。
- 负控只在独立detached树，脚本finally逐字节恢复；最终git status干净。不得将后续T-T83修复结果归给冻结#11。
- #15命令：python -m pytest tests/backend/retest/test_splice_validation.py -q -rs --tb=short -p no:cacheprovider → **15 passed/9 skipped**，与声明一致；恒真/规格自证未变，不代表9项接线业务已验。
- #26同路径命令 → **25 passed/0 skipped**；另python -m pytest src/backend/selfchecks/test_tb136_splice.py src/backend/selfchecks/test_tb136_preparation.py src/backend/selfchecks/test_tb136_precision.py -q -rs --tb=short -p no:cacheprovider → **38 passed**；两项数字均复现，只复跑已有用例不冒充新独立覆盖。
- #26首轮正常解释器缺pyarrow导致收集error；旧venv启动又遇临时目录故障，已终止。随后在仓库外RV02-arrow目标安装Arrow/Pandas，正常解释器完成最终复验；环境问题不计业务失败。
- 三PR各自声明的secret_scan两文件均独立复跑0阻断/0告警；各自单笔实现git diff --check均通过；未把#26基底额外33笔提交算成本次两文件扫描。
- #26 GitHub base=be/T-B136@834c9ff，PR整体34提交/44文件；本次只证其9beee6e接线与38项后端自检，不替代堆叠链/全PR范围复核。
- 原始证据F:/workspace/team/status/RV02-pr11-defaults.log、RV02-pr11-negative.json及4份negative日志、RV02-pr15-tests.log、RV02-pr26-tests-equipped.log、RV02-pr26-selfchecks.log；负控脚本同目录RV02-pr11-negative-control.py。
- 总结：#15/#26抽查数字通过；#11正向数字附既有失败，负控声明存在实质缺口，请编排者通知作者/合入方核定依赖修复顺序；r2未读/未动。
- DeepSeek：未用，独立冻结验收与门禁负控不外包。
申请新任务：r2正式发布后的R1–R5冻结核验优先；可接#11严格门禁修复终版复验。
