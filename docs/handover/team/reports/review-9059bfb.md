# 评审 9059bfb（T-B60：基于权威证券主表的候选准入保护）：逻辑可推，CI 会红
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- assess_master 的规则：hold/wait、主表里没有的证券、不可做策略的类型、已退市或退市日已到，一律拒绝；名单缺失也拒绝；未知上市状态直接报错；退市整理期只拦 buy/add，不拦卖出（§2.5.11）。
- run_with_master_guard 在保存点内对该证券主表行加 FOR SHARE 锁，再执行写入，自身不提交事务。
- 实测：tb60 45/0 通过（本机隔离 PG，unix 套接字，--network none，全部回滚）。tb58_master 也在同一环境下复跑，27/0 通过。
- **B5（后端）**：app/signals 和 selfchecks/tb60.py 共有 49 个 ruff 错误，2 个文件未按 ruff format 格式化，CI 的 backend ruff 会红。mypy 没有新增错误。
- 待裁定（不计入 B/M）：事件与状态交接（signal_events / candidate_signal_events 的写入边界）、遗留数据证书归属。由 plan 另行裁定。
- 注：本组件目前还没有生产调用点（模块文档已写明），离线通过不代表 signal-rt 已经运行。
