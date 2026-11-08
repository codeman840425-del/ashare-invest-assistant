# 评审 1f6965d（worker 改用 aia_api 连库；grants.sql 显式授予 worker 所需 DML）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 与 plan 7.3 第 8 条一致：worker 走 DATABASE_URL=*db-api-url，DB_ROLE_OF 已登记 worker=aia_api。
- $worker$ 段逐项授权并自检：cooldowns 的 SELECT/DELETE；import_rows 的 SELECT/DELETE；batches 的 SELECT；import_files 的 SELECT，以及仅限 deleted_at、storage_path 两列的 UPDATE。没有给 DDL。
- 核对 purge_expired_raw_files：FOR UPDATE 只锁 import_files，UPDATE 只写上述两列，与授权吻合。
- 实测（在 94cddd8 上）：apply-roles 跑两次 rc=0；verify-roles 71 OK、0 FAIL。
- B/M：无。
