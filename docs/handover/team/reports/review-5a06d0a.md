# 评审 5a06d0a（前端 T-F27，契约 #37–#40）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 与契约一致：草案的 not_found 改为 400 VALIDATION_ERROR fields[signal_ids]；blocked/active 一律显示 SIGNAL_NOT_EXECUTABLE；告警 message 原样显示（由 React 转义，没有 innerHTML）。
- 实测：eslint 0 警告；tsc 通过；vitest 669 通过、1 跳过。
- B/M：无。
