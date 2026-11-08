# 评审：d083641 test(frontend): T-F14 跟进——心跳超时用例改为注入 fetch

评审人：项目架构师　时间：2026-11-01（America/Denver）　方式：只读，/tmp 干净导出，pnpm 串行

## 结论：可推送（无 B/M）

## 改动
- `src/frontend/src/lib/eventStream.ts`：`EventStreamOptions` 增可选 `fetchImpl?: typeof fetch`，调用处 `(opts.fetchImpl ?? fetch)(url, …)`。生产代码中无任何调用方传入（grep 确认），默认行为不变；仍只请求后端相对路径、`credentials: 'same-origin'`。
- `t-f14.test.tsx`：心跳超时用例改为注入假 fetch（首次 503，其后返回只发 `: open\n\n`、中止时报错的流），断言（调用次数 ≥3、最终 closed）未削弱。

## 越权核对
- 改动的测试是 `src/frontend/src/**` 下与组件同处（colocated）的测试，由前端提交 7b47ace 创建；vite.config 的 vitest `include` 即为 `src/**/*.test.{ts,tsx}`。
- 计划 §5 把 `tests/`（含 `tests/frontend/`）归测试角色，§6 写 `pnpm -C src/frontend test` 指向 tests/frontend；实际仓库前端测试一直 colocated，T-T01 报告 §6.1 已记录该偏差。
- 判定：**不算越权**——只动前端自有目录内、前端自建的测试，外加本模块一个测试注入点。

## 验证
- 在 c4329bc（含本提交）导出上：typecheck 0、lint 0、`vitest run --no-file-parallelism`：38 文件通过 1 跳过，584 通过 1 跳过，无未处理错误。

## 问题
- n：`fetchImpl` 注释已写“测试注入用”，建议保持不在业务代码使用（可加 lint 约束或 `<at>internal`）。

## 谁做什么
- 前端：无必改项。
- 架构师：计划 §5/§6 补一句“组件 colocated 测试归前端，tests/ 归测试角色”（与 c4329bc 同一条，见 review-c4329bc.md）。
