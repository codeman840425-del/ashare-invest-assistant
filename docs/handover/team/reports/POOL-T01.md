# POOL-T01：T-T35 第二梯定点修复（北京时间 2026-11-11）
- 分支 ds/T01；基线 465e02046fa8d971897603742497444f884e89a2；冻结代码 0ac8553d980db96d02eeada7c5acbe4258c53b8d（仅本地，未推送/未合入）。
- 授权：编排者群内明确允许修改 test_tb86_history.py、test_tb86_offline.py、test_tb70_replay.py；无业务/probes/迁移改动。
- 两个 T-B86 模块在 Windows 于 fcntl/探针导入之前 module skip；Linux 不跳过，原有网络拒绝和合成凭据/临时账本保护不变。
- T-B70 集成断言从固定 0020 改为本分支 ScriptDirectory 唯一 head；不读 alembic.ini、不连库发现 head；冻结基线实测唯一 head=0034。
- 新增迁移图零头/多头拒绝负例；数据库仍须 require_isolated 且版本与图 head 完全一致，未放宽隔离或版本判断。
- Windows 命令：PYTHONPATH=src/backend python -m pytest src/backend/selfchecks/test_tb86_history.py src/backend/selfchecks/test_tb86_offline.py src/backend/selfchecks/test_tb70_replay.py -k 'migration_head or synthetic_manifest or positions_preview' -q -rs --tb=short -p no:cacheprovider。
- Windows：6 passed、2 modules skipped、3 deselected；一条既有 Starlette 弃用警告。两个 skip 是平台限制，不代表业务通过。
- Linux/WSL 命令：PYTHONPATH=src/backend /tmp/aia-T01-test/bin/python -m pytest src/backend/selfchecks/test_tb86_history.py src/backend/selfchecks/test_tb86_offline.py -q -rs --tb=short -p no:cacheprovider。
- Linux：47 passed、0 skipped；仅合成数据和临时账本，依赖安装在独立临时 venv；无真实麦蕊调用、无共享/生产库访问。
- 原始日志：F:/workspace/team/status/T01-windows.log、T01-linux.log、T01-linux-frozen.log。
- ruff 三文件通过；secret_scan 三文件 0 阻断/0 告警；git diff --check 通过。
- 遗留：T-B70 专用 PG/Redis 集成未跑；Docker/socket、alembic locale、其他第二梯项仍待对应负责人，不能据本单宣称设施错误归零。
- DeepSeek：未用，平台边界、隔离守卫和验收均本地核对。
申请新任务：按待办池领取 T-02；r2 发布后按已裁定清单冻结核验。
