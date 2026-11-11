# POOL-T08：测试线三PR描述与证据收口（北京时间2026-11-11）
- 基线465e020；ds/T08仅新增报告/脱敏XML/看板，不改三个已推分支或业务代码，不推送/合并。
- 冻结#42= b939963d306517a427131866478c1b4bfd0e603a，base ds/T02=9576a3e；#43=8eca8bc94fbef434f76b625a0f3e50c9e86831de，base ds/T01=59d88a9；#66=8b79c0306ad662232dd75b1c576d554d8104410e，base main=465e020；本地干净且与远端头一致。
- #42复跑9通过/0跳过：golden/test_golden.py、unit/test_tb117_session_filter_t_t61.py、contract/test_contract_stub.py，-k 'comparator or cases_directory or harness or cross_lunch or old_date or empty_session or catches_violation'；含真实属性测试与坏响应负例，不访问live_schema。
- #42仅PYTHONPATH追加仓库外T03-optional固定依赖；未重跑整树收集，1598/1692沿用原冻结代码9491f63证据，不算本次新验收。
- #43新增复跑6通过/0跳过：selfchecks/test_tb70_replay.py -k 'synthetic_manifest or positions_preview or migration_head'；仅验证原有六项可移植子集。文档单仍无实现变更，4项迁移候选和3项真库测试仍未验收。
- #66复跑60通过/1真PG平台跳过：integration/test_tb28_isolation_config.py与test_tb63_signals.py；纯合成Docker元数据含拒部分覆盖/异常网络挂载负例。Linux31通过沿用34ec476旧证据，本次不重跑Linux/真库。
- 命令公共项：Windows共享后端venv python -m pytest <上述文件及-k> -q --tb=short -p no:cacheprovider --junitxml=<输出>；PYTHONUTF8=1，PYTHONPATH=<各冻结worktree>/src/backend；#66另加-rs。
- XML：本报告同级T08/pr42.xml、pr43.xml、pr66.xml；仅移除机器hostname，保留case/结果/时间并附冻结SHA与原XML摘要。T08/manifest.json列出完整SHA、结果、双扫退出与XML SHA256。
- 原始XML/日志留仓库外F:/workspace/team/status/T08-pr{42,43,66}*；XML不是数据库/API集成通过证据。
- 三PR分别以实际base..head扫描：secret_scan files=6/3/6文件、range=8/3/6版本，全部0阻断/0告警；gitleaks8.30.1各范围0命中/退出0，diff --check全部通过。
- PR正文收口：列完整远端头/堆叠/实扫范围；#66纠正为T-B63身份参数化，明确旧closeout仅方案；#42删去“CI有无依赖都绿”泛化声明；#43区分历史未跑与本次6项复跑。
- XML计数及哈希发布到各PR评论；完整XML随ds/T08本地证据交付，由Chief决定推送，未推送前不声称GitHub可下载完整XML。
- 未跑全量测试/coverage；未操作真实Docker/PG/Redis/麦蕊/凭据/用户栈，不改他人索引与WIP。
- DeepSeek：未用，三PR冻结验收、安全扫描与最终描述核对由测试本地完成。
申请新任务：按池顺序接T-09时序抖动诊断；r2正式发布后R1–R5冻结核验优先。
