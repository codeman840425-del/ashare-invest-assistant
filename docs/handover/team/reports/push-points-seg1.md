# 第一段推送点（2026-11-07 13:25 MDT，架构师）
前提：origin/main = 61b0edf。本地 main 不要变基（2954b6c 的 gitleaks 豁免指纹写死了 3e5e288 的哈希，变基后哈希变化，指纹失效），用合并保留哈希。
1. 推 d5dd1f8 到 origin/main（61b0edf 快进到 d5dd1f8）。必须和第 3 步同一轮推送：d5dd1f8 单独推时总覆盖率是 0%，backend 作业会红。
2. 在 d5dd1f8 上合并本地 main 的 1c62952（6b44d87 之前的最后一个提交），推合并提交。1c62952 已包含 3e5e288 到 2954b6c，以及中间的 docs 和已评提交，全部可推；3e5e288 和 b3aab3c 在同一条链上，会一起推上去。
3. test/T-T01 推到 8cfa952（基于 d5dd1f8），可推。
4. 1a86cb9、ef123be、1af8543 和 T-O14 在 main 顶端，要等第二段评完再给推送点。
推完后 backend 作业仍是红的，原因是领域包覆盖率不达标（M，后端）：app/domain 65.7%、app/importing 71.8%，门槛 90%。这不是本段引入的。
m 级问题（不阻塞）：
- 运维：verify-roles 缺 aia_maint 的 3 条拒读断言；grants.sql 第 16 行注释过时。
- 后端：tb51 要求库里先有 2 行证券，文档没写。
- 前端下一项建议：vitest 时序稳定化，用假定时器替代 749b6fc 放宽的 20 秒总时限。
逐个提交的评审见 reports/review-{3e5e288,b3aab3c,fb4104a,a2d2b74,d860970,1398351,7f3f9ba,2954b6c,1a86cb9,8cfa952}.md。
