# POOL-T07：integration固定路径参数化（北京时间2026-11-11）
- 基线465e02046fa8d971897603742497444f884e89a2，分支ds/T07；代码冻结34ec476fedcb448a6d14c80821251cbbc081419f；仅本地未推送/未合入。
- 实现范围仅tests/backend/integration：tb28_isolation参数化专用容器名/socket/卷，新增纯元数据守卫自检；T-B63用同一配置socket调用tb60，仅真PG用例加Windows skipif。
- 三参数AIA_TB28_PG_CONTAINER/SOCKET/VOLUME必须同时显式提供，部分覆盖/非法路径或名称在Docker前拒绝；不设置时保留历史默认身份；参数不等于资源授权。
- none网络/无端口/运行态/两项精确挂载/共享与父子挂载拒绝均保留；PurePosixPath确保Windows也按Linux元数据语义比较；Docker失败继续拒绝，不回退共享库。
- 冻结Windows：python -m pytest tests/backend/integration/test_tb28_isolation_config.py tests/backend/integration/test_tb63_signals.py -q -rs --tb=short -p no:cacheprovider → 60 passed/1平台skip。
- 冻结Linux：仅test_tb28_isolation_config.py同参数 → 31 passed/0skip；全为合成inspect元数据，autouse禁真实Docker，未运行真PG那45条原断言。
- 31项守卫正反例含6种局部覆盖、非法身份/路径、错网络/端口/挂载、同源与父子共享、异常不回显；T-B63另29条纯逻辑Windows仍运行，未整模块skip。
- 参数化辅助模块/新增自检ruff通过；原T-B63继承9条lint、修后仍9条，诊断多重集无新增，不夹带格式清理。
- 文档docs/runbook/POOL-T07-integration-resource-plan.md列明tt21/tt22全局连接改写/CREATE DB副作用、OUT/PG/Redis/身份清单参数方案、Linux专库依赖与清理责任。
- 有意不改：旧closeout适配器、失效历史取证F0610–F0612、P2N10真实链、src/backend的16个固定socket自检；不能只改路径后连共享库或把失效取证重新记通过。
- 剩余责任：运维提供network=none独立PG/Redis、专用socket/卷与最小身份；后端核schema/head/原断言及适配器边界；测试核清fixture与清理责任后再冻结定点真库复验。
- 日志F:/workspace/team/status/T07-{windows-frozen,linux-frozen}.log；lint JSON T07-tb63-ruff-{before,after}.json。无真实Docker/DB/Redis/麦蕊操作，无全量测试/coverage/动栈。
- secret_scan改动代码+文档0阻断/0告警，git diff --check通过；生产业务代码和迁移0改。
- DeepSeek：未用，隔离身份/权限边界与冻结验收本地处理。
申请新任务：r2落盘后按R1–R5冻结核验；后续closeout显式资源配置与真实设施需另单。
