# T-09：四文件前端时序抖动诊断

北京时间2026-11-11；测试源码冻结 `24e4ba6c665db939e3d10cd9f591fdb43a2d94ee`（F-10初版，4项用例），不是已经追加F-12/F-13的PR #68新头。前端tree=`8e9d7e5788da696674db976ca3ed51d7e58d7c97`，pnpm-lock SHA256=`b18a99dbafd1d9b926cd6c1b427be405387f6bd9912157481dae5de5138aa991`，Vitest5.0.5。测试结论不回套到main或后续前端提交。

## 实测结论

本机忙时存在**并发敏感的首屏等待失败**。原始配置四文件四worker、两次同配置复跑和可选追踪四worker均出现失败；同四文件一worker、两文件二worker以及各文件单跑均通过。未改断言、mock、Testing Library配置、任何超时或重试；预加载原本已在beforeAll执行，不能把本次问题直接归为“漏加preloadRoutes”。

本轮支持“并发下认证→档案→子页签就绪链变慢、超过默认1000ms异步等待”的机制。主机CPU繁忙和低可用内存是并发背景；没有独占机器或内存/CPU单因素控制实验，不能进一步断言唯一瓶颈、内存泄漏、业务无缺陷或所有CI机器必抖。

## 有限对照矩阵

四文件固定为`src/pages/stock/t-f10.test.tsx`、`src/pages/t-f03.test.tsx`、`src/pages/t-a09.test.tsx`、`src/pages/t-f22a.test.tsx`；默认pool=forks、isolate=true；除了maxWorkers及文件列表，不改变运行设置。

| 实验 | worker | 通过/失败 | 进程墙钟秒 | 失败节点 |
|---|---:|---:|---:|---|
| 原始四文件（未加追踪） | 4 | 57/1 | 原日志留存 | F-10首个指数页面 |
| 四文件复跑1 | 4 | 57/1 | 27.277 | F22a证书横幅首次渲染 |
| 四文件复跑2 | 4 | 56/2 | 25.118 | F03行情头首次渲染、F10首个指数页面 |
| 四文件串行 | 1 | 58/0 | 69.483 | 无 |
| F03+F22a两文件 | 2 | 41/0 | 25.219 | 无 |
| F10单文件 | 1 | 4/0 | 15.934 | 无 |
| F03单文件 | 1 | 14/0 | 13.226 | 无 |
| A09单文件 | 1 | 13/0 | 10.124 | 无 |
| F22a单文件 | 1 | 27/0 | 12.805 | 无 |
| 加追踪的四文件 | 4 | 57/1 | 不与无追踪耗时直接合并 | F10首个指数页面 |
| 加同款追踪的F10单文件 | 1 | 4/0 | 不与无追踪耗时直接合并 | 无 |

这是有限样本，不估计长期失败概率；第二次四文件为温缓存，不能当独立冷启动样本。原始失败均保持非零退出，矩阵工具也因观察到失败退出1，不用“最终单跑绿”盖掉失败。

## 请求链与事件循环

可选追踪只记录测试名、相对请求pathname、耗时、已出现的testid和事件循环最大延迟；不记录请求头、query值、响应体、Cookie或证书。原测试和Vite配置不改，包装配置仅追加setup。所有数字以该用例beforeEach为零点，不是findBy计时器启动点。

同一个F10首屏用例：

| 观测 | 四worker失败 | 单文件通过 |
|---|---:|---:|
| 读取asyncUtilTimeout | 1000ms | 1000ms |
| `/me`请求开始 | 1389ms | 354ms |
| 档案请求完成 | 1475ms | 365ms |
| factors请求开始/完成 | 2358/2640ms | 493/506ms |
| 用例结束 | 2756ms | 563ms |
| 事件循环最大延迟 | 563ms | 155ms |
| 结束时观察到tab-factors | 否 | 是 |

四worker失败时factors请求已经以mock响应完成，结束时无pending路径，但目标DOM仍未出现；单文件相同断言成功。请求等待、React提交与定时器调度共同拉长就绪链，不能把所有时间归给MSW或把请求完成等同于DOM已经提交。

8逻辑CPU采样：矩阵各档CPU平均99.94%–100%，独立CIM读数100%；可用物理内存最低四worker约0.75GiB、串行约0.79GiB，单文件约1.24–1.49GiB。后续CIM空闲回升至约9.12GiB，说明负载随时间变化；没有进程归属或内存泄漏定性。诊断工具未启动压力进程、未停止其他任务。

11份原始/矩阵/追踪日志均未出现`Value is null`或Vitest的`Vitest caught`未处理异常汇总；有HydrateFallback及act警告，保留在原始日志。本次没有复现图表错误，不能以外单的既有图表噪音解释本次失败，也未修它。Vitest5 JSON不提供未处理异常数字，不能把缺字段当0；交付evidence.json使用日志banner布尔值，注明原始早期摘要默认0字段不可用。

## 稳定化建议（未更改CI或超时）

1. 本机资源紧张时，该四文件定点组显式`--maxWorkers=1`，保留失败退出和全部断言。本次58项全过是有限证据，不能宣称永久无抖动。两worker两文件通过不能推出四文件两worker也通过。
2. 将组间并行交给有资源预算的调度；避免多个完整前端进程同时预加载所有路由。待可用内存和CPU窗口恢复后再另单验证更高并行度，不在r2忙时持续压测。
3. 如需缩短耗时，另派前端将F10两个HTTP形状用例与完整页面路由预加载分组，或减少与目标无关的首屏依赖；须保留相同真实消费/断言，不能仅为变绿替换业务实现。本单只提出建议，不实施。
4. 不加全局超时、不加retry、不用重复到绿的脚本、不忽略unhandled errors。未来真正的未处理异常单独冻结/归因。

## 复跑工具

`tests/tools/frontend_timing.py`只允许固定四文件与最多3次四worker复跑；默认2次，再跑串行、两文件及四个单文件。它核对冻结前端tree/工作树未改、拒绝仓库内输出及覆盖已有单轮证据，保留原生退出码/JSON/log，并采集聚合CPU/可用内存；不读取进程名或环境全集。每轮独立Vitest进程，沿用锁文件和缓存，不安装依赖。

在本任务隔离worktree根目录，使用已安装的Node和Python：

```text
python tests/tools/frontend_timing.py --node <absolute-node.exe> --output <new-external-directory> --frozen-sha 24e4ba6c665db939e3d10cd9f591fdb43a2d94ee --repeat 2
```

可选追踪（从该worktree的src/frontend执行；环境变量只指向仓库外本轮证据目录）：

```text
AIA_TIMING_TRACE_DIR=<external-trace-directory>
node node_modules/vitest/vitest.mjs run src/pages/stock/t-f10.test.tsx src/pages/t-f03.test.tsx src/pages/t-a09.test.tsx src/pages/t-f22a.test.tsx --maxWorkers=4 --config ../../tests/tools/frontend_timing.config.ts --reporter=default --reporter=json --outputFile.json=<external-result.json>
```

完整原始材料在仓库外`F:/workspace/team/status/T09-*`；脱敏对照、原报告哈希和选定无payload请求时间线在`docs/handover/team/reports/T09/evidence.json`。本单只运行相关58项集合，不跑全量/coverage，不访问真实服务、凭据、Docker、PG/Redis或r2在写产物。
