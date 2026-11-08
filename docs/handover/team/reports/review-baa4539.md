# 评审 baa4539（T-B52 证券主数据同步：沪深北三所列表、退市、更名、北交所代码对照）：可推（CI 绿，失败时保守），但部署前要先补 M1
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在干净导出或临时克隆 /tmp/rv3 里跑，只读，没有推送，没有调用麦蕊。
- 实测：ruff check 0 个错误；mypy --strict 通过；tb52 81/0 通过（本机隔离 PG+Redis，全部虚构数据）。
- 符合 plan 4.6：整份拒收有 4 种情况；连续 2 份快照缺失才置 missing_from_list；钟点排程带 Redis 锁，失败重试 3 次；首次导入不触发 reconcile_vendor。
- **M1（运维）**：resolve_master_root 在 local/test 以外的环境里，没设 MASTER_SNAPSHOT_PATH 就返回 None，jobs.py:164 直接报 RuntimeError。到 aa858a8 为止 compose 都没给 worker 设这个变量，也没挂快照卷，所以生产上主数据同步每次都会失败，并写入 master_runs failed。
- M1 的修法：给 worker 加 MASTER_SNAPSHOT_PATH 和专用卷，在 check_secret_boundary 的 DATA_VOLUMES 里登记，并确认 worker 能访问三所的地址。
- m（后端）：sources.py 用标准库 urllib 直连交易所，没有走统一出口代理配置。需要确认这符合 plan 的出网约束。
