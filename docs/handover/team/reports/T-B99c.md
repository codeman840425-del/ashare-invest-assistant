# T-B99c：RV-06 并发窗口返工（2026-11-09，北京时间）
- 基线 a41794b（含T-B99b）；分支 tb-T-B99c；代码 3322affc3360c5444f67cd09ae34fd211396f32d；仅本地，未合回/推送/部署。
- STOP：T-B05每≤0.25秒等待重映射，预留后/发送前再查；T-B86同样在预留后重映射，0 HTTP仍保留原128台账预留事实。
- STOP写入和读取共用判定：有效普通目标才成立；失效软链/异常哨兵闭锁，FileExistsError不再直接算成功；不复制旧内容。
- 发送互斥：本人控制事务与最终检查至HTTP共用用户级PG事务锁；暂停/hold/替换/删除均接锁；适配器及真实连接构造后再检查。
- 顺序保证：暂停先提交则0 HTTP；发送先取得锁则暂停等待其结束，暂停成功返回后不再按旧状态发出请求；已发HTTP不能撤回。
- 绑定：随机UUID文件名；独立运行时随机密钥的HMAC仅在0600 SQLite保存，secure_delete/DELETE journal/内存临时表，不读DB HMAC或APP_MASTER_KEY。
- 清理：最长30天，访问到期清理；心跳含replay/全局暂停时清理删除/注销关联，冷却删除至paused_until（空截止最多删除后30天）；无引用HMAC擦除。
- halt/预算事实不删；清理后的遗孤halt/未知在途/最近一分钟账保守全局闭锁。旧指纹格式仍拒发，须运维另单迁移，本单未触碰真实共享目录。
- 验证回执有效期必须正数且≤30天，与日志去重期对齐；过期/未来回执拒读。每证书独立consumer group，无关旧pending不再阻塞本人兜底。
- 隔离定点52通过（37项新增+15项相关正链/权限用例）；真实aia_api/aia_ingest、合成HPKE/HTTP；覆盖检查后暂停/删除/全局暂停/STOP/撤回执。
- POSIX探针与门禁34通过、4未选；Windows uv定点25通过、3软链权限跳过、43未选；Linux相应软链用例通过。
- 受影响模块Ruff通过；common既存53、增加0；diff --check通过；14个源码/说明文件密钥扫描全0，报告另扫。
- app-only生产镜像导入通过（无probes挂载）；Linux镜像无uv，沿用离线python -m pytest与本地测试包；未放宽生产权限。
- 证据：F:/workspace/team/reports/T-B99c-{races-tests,posix-tests,windows-tests,prior-guards-tests,secret-scan}.log；专用PG/Redis及本任务匿名卷已核标签清理。
- 未做真实外呼、用户库读写、迁移、G7或实跑放行；主目录team-b未包含本分支修复，须先RV-07。
- DeepSeek：未用，原因本单为安全与并发修复、负例和最终判定，不适用机械外包。
申请新任务：由编排者转RV-07，按复核结果安排必要修复或定点验收。
