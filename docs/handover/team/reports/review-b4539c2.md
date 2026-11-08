# T-B61｜b4539c2 评审
结论：B=0，M=3；不可作为完整 T-B61 推送点，待后端修复并补隔离端到端验收。
范围：仅该提交 diff＋作用域/配额/调度的定点核对；未执行真实麦蕊、容器或 daemon 操作。
M1：db/tables/vendor.py:33 source_licence_id NOT NULL，master/vendor.py:83–100 只枚举已有证书 id，漏 not_set；按新裁定改可空键/部分唯一索引、CHECK 和聚合 skipped 用例。
M2：ingest/vendor_lists.py:109–133 在释放批次行锁之后 fetch_results，两个 consumer 可同时看到 requested 并重复采集/扣额；二次锁只防重复落行，不保证 batch_id 外呼幂等。T-B65 须补独占处理与故障恢复。
M3：master/vendor.py 原 deadline_for(manual) 把周末/周一早间不存在的计划槽当截止；已由 36e3d76 修复，不能单推原提交作验收。
验收①：diff 有 worker→Stream→注入→事务→告警离线链；生产 workers/ingest.py 无消费接线，已拆 T-B65，不宣称生产可用。
验收②：apply_batch 行锁＋非 fetched noop；并发外呼仍有 M2。
验收③：三列表任一失败整批 failed；hsrl_real 独失败仍 fetched 且不修改冲突。
验收④：已有暂停/到期证书可 skipped，无跨证书回退；无 id 作用域漏记，见 M1。
验收⑤：更晚 reconciled 快照存在时 superseded；需隔离库验证并发，不仅源码断言。
验收⑥：requested 到期 expired；fetched 超30分钟 sweep 补 apply；failed 崩溃后重试恢复仍需 T-B65 验收。
验收⑦：消息严格白名单，日志异常不回显；本次未重跑角色权限与哨兵数据库端到端测试。
静态：该变更11文件 ruff PASS；8个 app 模块严格 mypy PASS（HEAD=36e3d76，后者仅改 deadline）。
相关测试：12 PASS；intents 72%、vendor_lists 60%、master/vendor 28%，总49%，低于90%验收要求，不冒称全链覆盖。
证据：rv7_test_vendor.py、rv7-vendor-tests.log、rv7-vendor-coverage.json（均本地 reports）。
未运行 selfchecks/tb61.py：硬编码他人 tb58/tb61 实例并 flushdb，数据库名也非 rv7-；遵守不动他人容器/库约束，不改测试绕过。
需后端：修 M1/M2，合入36e3d76；提供 rv7- 隔离端到端入口后补七点和权限负例、覆盖率证据。
