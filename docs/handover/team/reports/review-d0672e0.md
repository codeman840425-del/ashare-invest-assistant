# 评审 d0672e0（所有容器 json-file 日志轮转 10m×5，加 CI 检查）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- check_compose_logging 遍历 deploy/compose 下所有 *.yml，包括 dev 覆盖文件，逐个检查每个服务，nginx、worker、beat、ingest、db 都在内。
- 覆盖文件不得修改轮转参数（各文件锚点必须一致）；遇到 !reset/!override 合并标签直接报错。
- CI 新增了 check_compose_logging 步骤，强制检查。
- 实测：check_compose_logging 结果 OK，对应测试包含在 605 个通过的用例里。
- B/M：无。
