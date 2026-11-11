# PR #11 严格门禁接续（北京时间2026-11-11）
- 基线冻结PR #11=7787441e635818790d380945e216ff2a2f150668；本地分支ds/T05，修复代码冻结e0d11eb73228d97b2c3d10780f6061e3f60ea81b，仅本地未推送/未合入。
- 复用既有T-T83补丁cfea45a，cherry-pick到原PR头（e0d11eb），不重复实现、不改业务/config默认值。
- 仅改tests/backend/api_app/test_config_yaml_defaults.py：market_rules移出OWNER宽泛xfail；缺失必须fail；差异断言给明确路径。
- 旧头7787441负控（RV-02证据）：repo首段stamp_duty_sell_pct 0.05→0.07，准确节点test_repo_yaml_equals_plan_defaults[market_rules]为XFAIL/exit0；snapshot节点仍PASS，只比较快照与plan。
- 新头e0d11eb同样值扰动经AIA_CONFIG_DIR指向临时合成配置，准确repo节点FAIL/exit1；无XFAIL/skip。缺失market_rules.yaml同节点FAIL/exit1。
- 正常配置：snapshot_equals_plan_block[market_rules]、repo_yaml_equals_plan_defaults[market_rules]、key_defaults_market_rules共3 passed/exit0。
- 命令：python -m pytest tests/backend/api_app/test_config_yaml_defaults.py::<准确nodeid> -q --tb=short -p no:cacheprovider；环境PYTHONPATH=本冻结树src/backend。
- 验收脚本F:/workspace/team/status/PR11-strict-final-verify.py，JSON PR11-strict-final.json，日志PR11-strict-{normal,bad-repo,missing-repo}.log；旧负控RV02-pr11-negative.json。
- 全部改值在仓库外tempdir，无修改跟踪配置，git status干净（报告创建前）；未跑全量/coverage、未连库/动栈/调麦蕊。
- 原PR单文件既有share_class_list白名单失败不在范围，不据3项正常通过宣称整套全绿；原PR #11说明仍由原作者更正，不代改。
- 合入建议：先#11原快照同步，再本分支严格门禁补丁（或原作者按裁定吸收该补丁）；切勿把e0d11eb的新证据倒算给7787441。尚未改变任何PR头/base。
- secret_scan改动测试及文档0阻断/0告警，git diff --check通过。
- DeepSeek：未用，冻结负控与门禁复验本地完成。
申请新任务：请编排者核定修复提交/PR接续方式；r2发布后的R1–R5冻结核验仍优先。
