# 第二段推送点（2026-11-07 13:50 MDT，架构师）
接在第一段之后（d5dd1f8 加合并 1c62952），继续用合并，不要变基。
1. main 能连续推到 9ad51b8。本段代码提交都通过：6b44d87、c36b88f、d0672e0、749b6fc、1f6965d、5a06d0a、3820276、5c76866、94cddd8。中间的 docs 和已评提交一起推，链里没有必须同批推的提交。
2. 链停在 e6ca937（前端 T-F25，未评），归入第三段。f6c36ec、ac6c710、1a86cb9 已评可推，但都在 e6ca937 之后，等第三段。
3. B 级问题（后端）：逻辑和 selfcheck 都通过，但 CI 的 backend lint 会红，修好之前这几个提交不能推。
   - B1 ef123be：tb58.py 有 12 个 ruff 错误，且未格式化；
   - B2 1af8543：reconcile.py 第 104–115 行有 5 个 mypy 错误，第 104 行把 tuple 赋给 str，要修逻辑，不能加 ignore；
   - B3 1af8543：tb58_master.py 有 46 个 ruff 错误；
   - B4 20fe5d3：tb59.py 有 30 个 ruff 错误，且未格式化（20fe5d3 必须和 7c0548a 同批推）；
   - B5 9059bfb：app/signals 和 tb60.py 共 49 个 ruff 错误，2 个文件未格式化。
4. 推完后 CI 仍是红的：后端领域包覆盖率不达标（第一段已报的 M）。其余实测全过：pytest 1157 个通过，scripts/ci 605 个通过，verify-roles 71 个通过、0 个失败，前端全绿。
5. m 级问题（不阻塞）：
   - 运维：compose 没设 SITE_ORIGINS；verify-roles 在角色不存在时会留下 t_o11_* 探针用户；要复核 /securities 的 502/504 错误页是否仍带 no-store。
   - 后端：tb51 的前置数据文档没写。
6. 环境事故：评审清理时 pkill dockerd，停掉了共用的容器。aia-t01 那一组已恢复 healthy；tb58-isolated-pg3 和 tb61-isolated-redis2 没有重启，需要后端检查后重跑。
逐个提交的评审见 reports/review-<hash>.md，本段共 16 份。
