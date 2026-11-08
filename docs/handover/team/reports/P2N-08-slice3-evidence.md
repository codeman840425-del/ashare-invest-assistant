# P2N-08 切片3：RC5期满可部署接线证据
本地提交a27a7ff23a154ca1f84250e19d958e0a722d0d50（未推送）。最新优先级在健康表只读核验阶段改为worker/HTTP最小端到端，未遗留健康代码WIP。
## 改动
1. app/feedback/worker.py：risk.rc5_expiry，仅取已到期系统LOSS_STREAK_PAUSE、approved本人及未归档同属账户，按owner/id确定性排序。每实例独立事务；resume_due在事务中重读与加锁，事件/期限/受阻通知原子。选择后删除/撤销的已知错误只保守跳过，其他错误不吞。
2. app/workers/jobs.py：复用现有TASKS与schedule，间隔取既有quote_interval_s，无新增配置或外部调用。队列无caller-selected owner等参数，不提供代理替用户操作入口。
3. selfchecks/test_p2n08_worker.py：实际受限角色PG、专属Redis、真实登录虚构身份、既有实例与通知未读HTTP投影；禁止AF_INET外连，仅AF_UNIX。
## 验收与边界
5唯一节点：golden092 published到期恢复、retired受阻、simulating受阻、缺日历保持暂停共4；手动pause/跨账户/撤销用户/归档账户守卫1。真实read API对本人返回状态、他人404/零未读、匿名401。
测试真正经beat_tick→Redis→worker_tick→注册实现→aia_api PG→HTTP；只替换可信时钟与该测试的排程集合，无替换最终数据库状态/通知产物，无更改正式卡级别/G7。
期满前1微秒及复用已核验草稿偏移均不恢复；到期重复队列投递不增加事件/通知或改变只读结果；受阻通知实际表落地并经未读接口读到。
既有086纯日历五场景和091真实PG关键边沿/max沿前片结果，本片未重复验证全部场景。088/089未接；RC5真实评估快照生产者/触发worker与公开风险投影未完成；健康历史/权重持久化及HTTP/worker、unavailable重算/最早data_as_of后续。
健康状态全站版本一份、本人排序开关独立（plan2.8.2），与本片实例RC5暂停不可混用；本片不写strategy_health_daily、user_strategy_weights或策略lifecycle。
## 定点命令（cwd=src/backend，PYTHONPATH=.）
/tmp/rv7-backend-venv/bin/pytest -q selfchecks/test_p2n08_worker.py （新增最初4节点，4过，/tmp/p2n08-s3-worker.log）。
/tmp/rv7-backend-venv/bin/pytest -q selfchecks/test_p2n08_worker.py::test_worker_preserves_manual_pause_and_rechecks_account_and_user （新增守卫1过，/tmp/p2n08-s3-guards.log）。
无全量/coverage；未复跑切片1核心42节点。2源码mypy --follow-imports=silent与仅3路径ruff/diff通过；暂存3路径secret_scan staged阻断0/警告0。
## 隔离复现与权限
先mkdir -p /tmp/p2n08-s3-owned/pg /tmp/p2n08-s3-owned/redis；chmod 777 /tmp/p2n08-s3-owned/pg（只专属无凭据隔离目录）。
PG：docker run -d --pull never --name p2n08-s3-owned-pg --network none -e POSTGRES_HOST_AUTH_METHOD=trust -v /tmp/p2n08-s3-owned/p<path> timescale/timescaledb:2.31.0-pg16 -c listen_addresses=''。
Redis：docker run -d --pull never --name p2n08-s3-owned-redis --network none -v /tmp/p2n08-s3-owned/redi<path> redis:7.4.12-alpine redis-server --port 0 --unixsocket /data/redis.sock --unixsocketperm 777 --save '' --appendonly no。
仅本机现存镜像；初始原生redis-server不存在，未安装/寻密钥/联网，改用已有固定Redis镜像。PG初始化期间一次pg_isready无响应，启动完成后才测试；不算通过结果。
每节点复用切片2随机DB fixture，实际迁移head0027后读取原deploy grants（密码占位只设NULL），以aia_api登录且断言非superuser；root仅虚构种子/损坏测试。无需新增表或grants；既有SELECT/行锁、实例UPDATE、事件和通知INSERT在真实角色中实际执行，不改deploy。
测试后随机DB逐个清理；按各自创建时保存完整CID验证容器名称后仅stop/rm -v本片PG/Redis，确认无随机测试DB，删除本片全部空socket目录。本片无运行资源遗留；切片2 uid70空目录未动/未提权。
DeepSeek：复用reports/deepseek/P2N-08/24纯合成操作数中两条作期限前偏移，逐条核验；规则/安全/验收本地，无新外调，无源码/秘密/真实数据外发。
未启用生产beat/worker、未发送真人通知/SSE、未调用麦蕊/官网/证书/资金/G7；B90b/B86继续挂起，实际生产来源和B2缺口保持未验收。
