# review-7f94033（T-T28，仅测试）  结论：基线有依据、没有放宽；但不可移植 → B（测试员）
- 基线 json 锁定输入 SHA、已评审的修正 SHA、canonical 分析全树 SHA，以及精确的 changed_sections（10_cdr/4_capital/6_pb/7_share_class_lists/9_currency_unit/trading_calendar）；2 个旧失败保留为断言。依据是 T-B59（20fe5d3/7c0548a），属于严格校准。
- m：基线由后端产出，自证成分偏高；建议附一份人工核对的分节摘要。
- B1：test_tb58_replay_calibrated 依赖 `git show 8e8525e:`（CI 是 fetch-depth 1，且导出包里没有 .git）和 /tmp/tb63-replay-* 证据副本 → 3 errors。
- B2：tb28_isolation 依赖固定名字的容器 tb58-isolated-pg3、卷 hash 和 /tmp 下的 socket，CI 上 skip 或失败，signals 覆盖率也随之失真。
- 修法：证据入库成 fixtures，或改用 testcontainers 起 PG；另外 7bd93e6（T-T27 e2e）还没评审。
