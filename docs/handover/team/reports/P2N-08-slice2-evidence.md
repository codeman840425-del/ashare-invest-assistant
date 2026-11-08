# P2N-08 切片2证据（仅合成隔离，不是生产验收）
提交 ba4669d4221023fcd8ee27806a711385fb652c84；输入T-A33/36/37与当前契约，配置只两组特批键。
## 实现与界限
- app/feedback/pause.py 接收内部冻结评估receipt；所有数据有本人/账户/实例/有效版本、policy hash、as_of、snapshot hash和证据引用。并非客户端自报即可驱动的HTTP入口。
- append-only risk_events使用专用p2n08-rc5-cursor/v1保存内部观测游标；不伪装公开风险事件状态机，后续仍需公开投影/生产数据生产者接线。
- 首次已超阈值却无前值，返回rc5_previous_value_missing并保守建立基线；不将未知前值造0。真正源需提供可追溯历史。
- 自动暂停/延期、实例事件、cursor、期满受阻通知均在调用方同一事务；API原事件helper仅增加可选可信时钟参数，原调用不变。
- 实际YAML授权映射与内部恢复比例已补；不改其他配置，无迁移/新表/权限提权。
## 唯一相关节点与日志
共15节点：新模块13节点（086×5、配置1、真实暂停并发1、092×4、归属/回滚/缺证1、计数/回撤/max1）及旧core受影响配置/兼容2节点。
初跑 /tmp/p2n08-s2-first.log 为13过1失败，失败为同一时刻UTC与+08:00字符串比较；改aware datetime等值后复验。
/ tmp路径均本地：/tmp/p2n08-s2-final.log 3过（修复092、新增max、主链）；/tmp/p2n08-s2-guards-final.log 2过（最终共享锁、手动/禁用/回滚与主链）；/tmp/p2n08-s2-collected.log 15唯一节点。配置节点最终独立1过。
复现（cwd=src/backend，PYTHONPATH=.，venv=/tmp/rv7-backend-venv）：pytest -q selfchecks/test_p2n08_pause.py selfchecks/test_p2n08_core.py::test_config_mapping_override_not_fixed_five_and_missing_closed selfchecks/test_p2n08_core.py::test_invalid_result_types_do_not_clear_streak_and_legacy_config_shape。
这是仅直接相关模块，不是全量；交付前仅受影响节点复跑，不把重复运行累加为数量。无coverage。
## 隔离PG与角色
自建p2n08-s2-owned-pg，timescale/timescaledb:2.31.0-pg16，network none、listen_addresses=''、仅Unix socket /tmp/tb70-p2n08s2-owned-pg，虚构trust认证。
可复现容器命令：docker run -d --name p2n08-s2-owned-pg --network none -e POSTGRES_HOST_AUTH_METHOD=trust -v /tmp/tb70-p2n08s2-owned-p<path> timescale/timescaledb:2.31.0-pg16 -c listen_addresses=''。
测试fixture为每节点创建随机tb70_p2n08s2_<uuid>数据库，真实alembic upgrade head（0027），只读原deploy grants以NULL替代密码占位后隔离装载；真实aia_api执行产品事务，断言current_user及非superuser，root仅虚构种子与损坏/缺日历测试。
已有授权已在此真实角色隔离演练通过；无新增grants/deploy改动。所用表：users/strategy_instances/strategies/strategy_versions/accounts读取及行锁，strategy_instances更新，data_snapshots/risk_control_settings/market.trading_calendar读取，risk_events读取/追加，strategy_instance_events与notifications追加。FOR SHARE/UPDATE所需现有权限也实际执行。
## 清理与剩余
各fixture禁止新连接、仅终止其随机测试DB连接并drop。清理前检查无tb70_p2n08s2_%库；核验完整CID aec8d35e8cf3419569719c721d5ea3be99fd70a8798ec594dca6090dd2278a05及名称后只stop/rm -v该自建容器。没有Redis或其他服务被改动。
空socket目录仍为uid70:1000、mode1775，当前uid rmdir被拒绝；已确认目录0项，无服务/卷/套接字残留；未提权或广删。
DeepSeek：复用已复核24纯合成操作数作为重放时间偏移，不新发私有源码或真实数据；报告目录reports/deepseek/P2N-08/。规则、安全、预期与验收本地独立完成。
未接生产worker/HTTP/公开风险投影，未真实发送通知/SSE，未访问麦蕊/证书/资金/私密/G7；健康持久化/RC6/重算等后续，不把本片当整项验收。
