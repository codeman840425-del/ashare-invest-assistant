# POOL-T04：Windows自检迁移预研（北京时间2026-11-11）
- 只读事实冻结ds/T01=59d88a9aa8b3a2dd69ef7ee730af0ef5c99f940b，代码0ac8553；文档分支ds/T04，未改三个selfcheck/probes本体。
- 交付docs/runbook/POOL-T04-windows-selfcheck-migration.md：逐函数依赖清单、最小子集、迁移步骤、真库冒烟前置与不迁移原因。
- AST盘点56实例：history17+offline30+replay9；历史Linux47通过不等于Windows可直跑47，T-01的Windows仅覆盖replay6项。
- 当前可直接跑6项：synthetic_manifest1、positions_preview2、migration_head正例1/负例2；本单未重跑，不套用历史结果。
- 先拆入口可新增4完整实例：offline的预算/计划断言、拒执行入口、全pending计划三项；history的connection不重连一项。当前fcntl顶层导入使其仍不能原样在Win导入。
- 需后端另单拆无POSIX纯模块并由原探针重导出；测试再迁移真实函数调用，不伪造fcntl、不抄常量自证、不放宽Linux锁/权限约束。
- 另有segment未释放、STOP前置、CLI未授权半条可拆前置语义；响应分类矩阵可新增，但不能替代原落账/熔断全链路证据。
- 必留Linux：reservation/inspect_counter真实flock、O_NOFOLLOW/getuid/0600/单链接/inode/fsync；history执行与finally查账，CLI授权路径SIGHUP另有Win缺口。
- replay另外3例依赖专库且写用户/证券/快照/导入，teardown不清全库；不是只读真库冒烟。固定Unix socket与拒IP守卫须另单设计，禁止接用户库或共享库。
- 无pytest/全量/coverage、无数据/证书读取、无网络/数据库/栈操作；只执行AST盘点和文档门禁。
- 验收建议：另派后端拆入口+测试4项迁移，Linux47原例、Windows6已有+4新增分别冻结复验；真库3例继续阻塞至设施/身份/清理责任齐备。
- secret_scan文档0阻断/0告警、git diff --check通过；代码本体diff为空。
- DeepSeek：未用，平台安全语义与只读分支审查不外发。
申请新任务：按本预研另派后端纯入口拆分与测试4例迁移；r2发布后的冻结核验保留。
