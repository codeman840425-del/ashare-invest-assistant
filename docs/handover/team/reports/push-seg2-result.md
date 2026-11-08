# push-seg2 结果（2026-11-07 13:54 MST）
- origin/main = 1c8d2fd94c4bc3eca92038927163b3dc11193f93（父 934648b + 9ad51b8，21 个提交）
- secret-scan 42412760929：success — <url>
- ci 42412760950：failure — <url>
  - backend：pytest 收集 241 个，全部通过（只有 tests/backend/unit 的 4 个文件）；coverage 提示 "No data was collected"，总覆盖率 0%（0/8425），app/importing 0/1406
  - 8cfa952（test/T-T01）的业务测试不在本树里；覆盖率仍为 0，原因是测试没有导入 app 代码，或覆盖率配置没采到数据
  - gateway-limits：上游删除后返回 504（应为 502），等 T-O14
- 另有 Dependabot 自动运行 42412775832（minimatch 升级）failure — <url>
- 未重跑，未改代码，未 merge 共享 main
