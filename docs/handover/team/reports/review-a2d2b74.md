# 评审 a2d2b74（前端：收益原值、refresh 以响应体为准 #36、放弃/失败批次不请求预览 #35）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 实测（pnpm 10，--frozen-lockfile）：eslint 0 警告；tsc 通过；vitest 41 个文件、644 例通过，1 例跳过。
- ImportWizardPage 对 discarded/failed 批次不再请求 rows，与 3e5e288 的 errors.csv 只给表头一致。
- m：749b6fc 记录过 misc-fixes-2 在干净检出、全量并行时 5.3 秒超时。这次本机两次运行都没有复现，因为 749b6fc 已把总时限放宽到 20 秒。在 749b6fc 推上去之前，CI 偶发变红的风险由前端负责跟踪。
- B/M：无。
