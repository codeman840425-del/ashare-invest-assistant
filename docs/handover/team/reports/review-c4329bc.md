# 评审：c4329bc test(frontend): T-F12 跟进——刷新用例放宽异步等待

评审人：项目架构师　时间：2026-11-01（America/Denver）　方式：只读，/tmp 干净导出，pnpm 串行

## 结论：可推送（无 B/M）

## 改动
仅 `src/frontend/src/pages/t-f12.test.tsx`：`configure({ asyncUtilTimeout: 5000 })`、个别等待加 `{ timeout: 5000 }`、第二次点击前等待 `sg-refresh` 重新可用。断言内容（409 文案、刷新后结果）未削弱；“等按钮可用再点”反而更贴近真实交互（刷新进行中按钮禁用）。

## 越权核对
- t-f12.test.tsx 由前端提交 05d8a16 创建，位于 `src/frontend/src/`，属前端 colocated 测试。**不算越权**。
- 计划文字与实践不一致（§5 tests/ 归测试角色，§6 前端测试命令指向 tests/frontend），T-T01 §6.1 已记录。

## 验证
- c4329bc 导出：typecheck 0、lint 0、vitest 串行全绿（584 通过 / 1 跳过）。本次按要求只串行跑，未复现并行偶发超时。

## 问题
- n：5 s 超时是治标；并行慢的根因（jsdom + 整套并发）未查。若后续仍偶发，测试角色可评估 CI 用 `--no-file-parallelism` 或限制 `maxWorkers`。
- n（架构师）：计划 §5/§6 明确测试归属——组件级 colocated 测试归前端；`tests/` 下的跨模块/E2E/契约测试归测试角色。

## 谁做什么
- 前端：无必改项。
- 测试角色：关注 CI 上并行跑的稳定性（可选）。
- 架构师：下次计划修订时补测试归属说明（不升契约版本）。
