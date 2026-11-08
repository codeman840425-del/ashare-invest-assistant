# T-B76 worker 新增操作清单（未执行授权）
- worker/beat 继续使用 aia_api；未加角色、未 SET ROLE、未修改部署/GRANT/迁移。
- SELECT market.trading_calendar、market.securities。
- SELECT app.users（实际仅 id/role/status）、accounts、opening_positions、trades、holdings、import_batches、broker_position_snapshots、broker_position_snapshot_items。
- SELECT app.strategies、strategy_versions、strategy_instances、strategy_card_versions、data_snapshots；feature_catalog 实际只读 feature_key/unit。
- SELECT app.watchlist_items、suggestions、plan_drafts、non_executable_reasons、reconciliation_runs、reconciliation_items。
- app.pipeline_runs：SELECT、INSERT、UPDATE(status,finished_at,stats,error)，用于调度意图/进度/恢复。
- app.daily_reports：SELECT、INSERT、UPDATE(status)；app.daily_report_items：INSERT。完成版不可变由已有触发器保护。
- 不需要 DELETE/TRUNCATE/DDL、版本生命周期/晋级/批准写权限或市场业务数据写权限。
- 本次验收使用既有专用隔离库测试身份，不能据此宣称 aia_api ACL 已通过；部署前由运维逐表核查，仅按上述最小集合处理并另获部署授权。
- 合成夹具建账、日历种子和测试角色数据操作仅在隔离库，不属于 worker 生产权限申请。
- T-A14续：应用/公共runner启动增加只读public.alembic_version；未应用授权，运维部署前核查各实际角色的只读权限。

- T-A16部分d5d6b62：API/公共worker启动新增只读app.engine_policies（同版本哈希守卫）；显式种子工具SELECT/INSERT仅人工指定目标执行，不是worker生产写权限；未GRANT/提权，实际aia_api ACL仍须运维核查。

- 54e8edb真实装配续：SELECT app.engine_policies/risk_control_settings；app.data_snapshots SELECT/INSERT；candidate_signals SELECT/INSERT/仅头状态UPDATE、signal_state_events INSERT；non_executable_reasons及reason_status_events SELECT/INSERT；suggestion_threads SELECT/INSERT/UPDATE(current_suggestion_id)、suggestions SELECT/INSERT/UPDATE(status,superseded_by_id)。仍aia_api，不GRANT/提权；实际ACL待运维核查。
