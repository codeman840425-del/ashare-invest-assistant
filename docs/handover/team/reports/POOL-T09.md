# POOL-T09：前端并行时序抖动诊断（北京时间2026-11-11）
- 测试源码冻结24e4ba6c665db939e3d10cd9f591fdb43a2d94ee（F-10初版，非#68最新头）；前端tree=8e9d7e5788da696674db976ca3ed51d7e58d7c97，Vitest5.0.5；工作分支ds/T09，未改原测试、业务、mock、超时或CI。
- 原四文件四worker：57过1败；矩阵两次同档：57过1败、56过2败；失败分布F10首个指数页、F03首个行情页、F22a首个证书页，均保留非零退出。
- 对照：四文件一worker58全过；F03+F22a两worker41全过；单文件F10/F03/A09/F22a分别4/14/13/27全过，不能把单跑绿盖掉并行红。
- 追踪四worker57过1败、F10单文件4全过；同用例factors开始/完成2358/2640ms vs493/506ms，事件循环最大延迟563ms vs155ms，默认异步等待两档均1000ms。
- 归因边界：支持忙时并发导致认证→档案→页签就绪延迟超出等待窗；preloadRoutes原本已在beforeAll，不归为漏预加载；未证明CPU/内存唯一瓶颈、数据串扰或所有环境必现。
- 主机8逻辑CPU，采样各档CPU近满载（独立CIM100%），可用内存最低约0.75GiB；串行也忙，负载不独占且随时间变化，不据此认定泄漏或OOM。
- 11份日志未见Value is null或Vitest caught未处理异常汇总；保留HydrateFallback/act警告，未修图表。Vitest5 JSON缺异常计数字段，交付用日志banner布尔值，不将缺字段当0。
- 建议本机忙时对该四文件组显式maxWorkers=1，保留失败门禁；不增全局超时/retry、不重复到绿；缩小路由预加载与HTTP/页面测试拆分需前端另单，不在本单实施。
- 新增tests/tools/frontend_timing.py及可选config/setup：有限矩阵、聚合资源采样、只记路径和耗时，拒绝改动前端tree、仓库内输出与覆盖旧单轮证据；不记录header/body/query值。
- 交付docs/runbook/POOL-T09-frontend-timing.md及同级T09/evidence.json：完整对照、准确node名、原始报告哈希与无payload时间线。原始JSON/log/trace在F:/workspace/team/status/T09-*，不入库。
- 校验：Python定向Ruff/format、CLI帮助与冻结/输出边界拒绝；可选TS包装config/setup已在两档实际运行。修改脚本摘要字段后的边界校验不作为业务复跑。
- secret_scan本单文件及提交范围0阻断/0告警，gitleaks8.30.1 staged/range零命中，git diff --check通过；无全量/coverage/真实外呼/服务或栈操作，未读在写r2。
- DeepSeek：未用，受控实验、资源/安全边界、最终归因与验收本地完成。
申请新任务：r2正式三件套发布后的R1–R5冻结核验优先；可按本证据另派前端缩小页面测试依赖。
