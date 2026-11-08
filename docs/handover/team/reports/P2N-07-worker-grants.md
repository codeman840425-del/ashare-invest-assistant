# P2N-07 worker权限推导（未验证生产角色，不是GRANT执行/扩权申请已批准）
隔离实链实际连接aia_api、使用既有授权；尚未用生产worker身份演练，部署前运维需对照真实连接角色核验，不能把推导当已有授权。
USAGE：app、market schema；既有数据库CONNECT与通用worker基础权限不在此新增。
SELECT：app.users(id,status)、market.trading_calendar(date,is_open)，用于有效用户与真实交易日判定。
SELECT：app.action_plans、app.plan_versions、app.plan_conditions、app.data_snapshots；代码现用整行选择，按用户/账户/当前版本/PIT筛选。
SELECT：app.alert_rules(id)、app.alerts(id,user_id,dedup_key)，用于已持久化规则/条件去重。
UPDATE：app.action_plans(status,triggered_at,updated_at)，仅系统条件满足转换；无需改plan_conditions/version正文。
INSERT：app.alert_rules、app.alerts、app.data_snapshots、app.audit_logs；用于条件规则、一次性提醒、不可变评估回执、系统审计。
主键均显式UUID或gen_random_uuid默认；无新增sequence、DELETE/TRUNCATE、DDL或通知/SSE表权限需求。确认时信号状态/事件写入由已认证API角色执行，非此worker操作。
上述仅07新增作业的业务表操作；现有通用worker基础操作权限由运维按当前部署核验，本轮未读生产凭据/连接生产或共享库。
