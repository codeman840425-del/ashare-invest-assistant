# POOL-T02：整树收集 CI 守护（北京时间 2026-11-11）
- 分支 ds/T02；基线 465e02046fa8d971897603742497444f884e89a2；冻结实现 3d7504dbf690d0886be167ee25e1a5f379f32172；仅本地，未推送/未合入。
- 交付 tests/tools/check_collection.py、test_check_collection.py 与 README；CI 可直接调用，未改 workflow/业务代码/全局 conftest。
- 命令：python tests/tools/check_collection.py --output collection-summary.json（任意cwd，默认本仓库 tests/，下限1350可显式配置）。
- 仅收集，拒绝任意收集错误、pytest 非零退出、空集和低于下限；模块skip独列；不将收集成功写作业务通过。
- 忽略继承 PYTEST_ADDOPTS/配置 addopts 的筛选；固定 strict-config/strict-markers/importlib，保留pytest原生结果并独立检查failed collector。
- 冻结定点：python -m pytest tests/tools/test_check_collection.py -q --tb=short -p no:cacheprovider → 10 passed；守护定点tests/tools配--min-collected 10实测10 collected/0 error，退出0。
- 正反例覆盖：fixture/测试体不执行，缺依赖/语法错拒绝，退出码被hook改0仍拒绝，零项/缩量拒绝，skip单列，非法路径/根外路径/零下限拒绝。
- 真实整树：1596 collected / 4 collection errors，退出1；未修改465e020基线1586 collected /同4 errors，新增10项均为本单自检；未跑全量测试体/coverage。
- 4错为schemathesis、hypothesis、requests缺依赖及milestone tt21_head裸导入（节点详见JSON）；属既有依赖/测试设施，不在本单吞掉或声称已恢复零错。
- 原始证据：F:/workspace/team/status/T02-{baseline-collection,main-collection}.{json,log}、T02-guard-tests.log。
- ruff两文件通过；secret_scan代码与文档0阻断/0告警；git diff --check通过；无PG/Redis连接、无真实麦蕊、无栈变更。
- 适用范围：仅 tests/，不包含src/backend/selfchecks或scripts/ci/tests；收集会导入模块，脚本本身不构成隔离沙箱。
- DeepSeek：未用，收集判定及错误验收均本地完成。
申请新任务：请编排者补池；r2发布后执行已保留的冻结核验。
