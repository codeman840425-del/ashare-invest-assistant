# T-O30 机械准备（运维，2026-11-08 01:45 MST）：只收集，没改实现，没建库，没跑测试
架构裁定已核实：reports/T-A30.md 存在；提交 7f5b061 存在，并且就是共享主线已提交的 HEAD。
基线：7f5b06179f251f127066fc2c9d5f64944fad864a。T-O29 的 adf9fb4 不在里面。
T-O29 补丁：artifacts/T-O30-T-O29-adf9fb4.patch（git format-patch），sha256 55b16946efee6e0a676b147106e4d745def6422a1038b1b366d470ef9af4464b。在 HEAD 上可以 apply --check。
基线包：artifacts/T-O30-baseline.tar.gz，sha256 a54375dcab7ec16b2a24b164e37660278e9c621e302847a5497aa0463cb2d6f3，71 个文件。内容：
- deploy/db/roles、deploy/compose、secret-env.sh、migrations/env.py；
- 迁移 0001/0003/0013/0019/0020/0023/0024；
- app/db/tables、ingest（含 daily_lists.py）、workers、master、plans、cli/master_bootstrap.py；
- docs/plan.md（T-A30）。
背景：artifacts/T-O30-context/，含 T-A30.md、T-O29.md、上面的补丁和 README。
扫描：gitleaks dir 0；包内没有 .env 或 key 文件。secret_scan files 报 1 条 S7，在 docs/plan.md:29，是旧提交 4c75985 的内容，不是 T-A30 新加的；同一 HEAD 下 secret_scan tree 阻断 0。判断是 files 模式在 /tmp 路径下丢了仓库内的路径上下文，属于已裁定的类别，不是新秘密。
5 项预期映射（来自 T-A30；之前 T-O29 有 5 条不一致，这里给出新的预期）：
- 1 aia_ingest master_runs：INSERT/DELETE/TRUNCATE 和表级 UPDATE 都应拒，SELECT 和 UPDATE(stats) 应可；
- 2/3/4 aia_ingest 对 app.action_plans、alert_rules、alerts：所有权限都应拒；
- 5 aia_maint 对上述 app 表 id/user_id 的 SELECT 和 DELETE：保留，测试预期改为“应可”（删除 CLI 清单的既有设计）。
tests 建议（不改）：scripts/ci/tests/test_secret_boundary.py 引用了角色名，需要 cloud 看看是否要随之调整；src/backend/tests 里没有角色授权测试。
DeepSeek：未用，原因：权限收窄与定点安全判定不宜外包，本次也不需要框架。
