# T-B99b｜RV-05 六项修复，待 RV-06（北京时间 2026-11-09）
- 代码：c1a1cbdba339da0524eb5ed65ed330ec385b72c1；仅本地任务分支，未合回/推送/部署；本单真实麦蕊0、用户库读写0。
- P1-1：run_all 与 T-B86 真实入口在历史STOP提前退出前映射公共STOP；不复制/打印旧内容；common统一固定标记写入+flush/fsync文件和POSIX目录。
- P1-2：验证独立 root-owned 0444 回执，绑定本人/行UUID/时段/receipt_id、max_http_requests=1；DB按回执预留，多个意图合计最多1次；只有名单三次回执时不消费验证队列/扫描。
- P1-3：验证在解封后、预留后至HTTP前重查当次回执、本人approved状态、证书暂停/删除/管理员hold，全局暂停；并发撤权时HTTP=0。
- P1-4：名单每次发送（含等待后）读取Redis暂停键；Redis缺配置/不可用闭锁；验证同样逐次检查，不依赖heartbeat批次入口的旧结果。
- P1-5：四类发送必须先确认证书内容的私有不透明稳定标识；halt/分钟账按该标识，UUID只作私有映射，删重设同证书不能清闩/清预算。
- 绑定不读取DB HMAC或向ingest引入APP_MASTER_KEY；不透明标识不进API/报告；同证书旧UUID的IP次数合并，第三次升级一小时，旧限流通知不刷第二份。
- P2：每次名单HTTP前复核18:00窗口、截止、交易日/日历、当天批次；时钟回拨立即闭锁，不等待回拨追平后继续。
- Linux定点28 passed：六项负例、隔离库aia_api角色调用原删除/重设服务+HPKE、跨UUID分钟账/IP升级、三名单与真实Redis意图/兜底正链。
- POSIX探针/门禁定点32 passed、5 deselected；Windows uv run pytest定点23 passed、2 skipped、22 deselected（一个POSIX项及未启用独立DB项）。
- Linux/WSL复用既有镜像及本地pytest纯Python包（环境无uv）；显式文件/-k，不联网安装、不跑全量/coverage、不连用户库测试。
- 限定ruff通过；common/run_all原存53/176项遗留告警，新增均0；生产镜像仅挂app、不含probes的导入验证通过。
- secret_scan files：代码13文件与本报告另扫，均0阻断/0警告；提交前diff --check通过；无迁移/无权限放宽。
- 原始日志：F:/workspace/team/reports/T-B99b-{guards-tests,posix-tests,windows-gate-tests,secret-scan}.log；lint基线比较脚本同目录。
- 运维说明已同步：验证回执独立挂载；共享原生POSIX目录的写入者必须同UID（文件0600）；绑定/分钟账不能删来重置。
- 旧UUID格式halt保留并保守闭锁，旧未知在途/最近一分钟账也闭锁；须授权运维核清迁移，未提供自动清闩/清计数命令。
- 请Chief转RV-06；通过前不放行实跑。任务分支/工作树保留供复核；专用测试PG/Redis已核标签清理。
- T-B100已恢复收口：代码1227b65、本地team-b合并09e54f2；三卡已入本地库draft、G1–G6已跑，G7 untouched；详见main的T-B100报告。
申请新任务：转RV-06；T-B100转定点验收，不代做G7。
