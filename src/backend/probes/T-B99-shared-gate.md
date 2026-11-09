# T-B99 共享门禁运行说明（T-B99e / R3A，北京时间2026-11-09）

实现不授权部署、外呼或解闩；真实执行仍须Chief当次派单，名单、验证、探针分别记账。

## 接线前置

- ingest镜像只需app，不依赖probes目录。真实探针用同版后端Python环境（含SQLAlchemy、psycopg及requests）；缺数据库依赖/身份参考时闭锁，不能退回本机时钟。
- 唯一原生POSIX物理目录挂到ingest及两探针，MAIRUI_SHARED_STATE_DIR必须一致；禁止副本、软链、临时层或Windows目录替代。建议0700，文件0600；所有发送方及停机写入方使用同一受控UID，只有同组不足够，不能chmod777。
- api/worker不挂共享目录或运行时关联密钥；本人DELETE/替换由0029数据库触发器在原事务内缩短保留或删关联，不再依赖心跳/跨目录文件写入。
- 新增单一迁移head=0029：ingest_private私有绑定与scope历史、DELETE触发器及数据库now()清理。RLS仅允许aia_ingest看/写关联行，即使既有角色脚本重新广授表权限，api/maint也不能取到tag。存有scope事实时拒绝降级，不删事实凑空表。
- 产品ingest复用现有Settings中的aia_ingest数据库接线；独立探针必须显式提供MAIRUI_SHARED_DATABASE_URL_FILE，指向不可组/其他写、非软链、单链接的私有DSN文件（建议0400）。不得把值写入命令、policy、日志或报告；本单没有读取/生成真实DSN。
- 运维只在非密文视图核对MAIRUI_SOURCE_LICENCE_ID及policy归属；每次探针发送也重新核对数据库关联，并与本人API暂停/DELETE共用用户级PG事务锁。关联失效或数据库不可用即0 HTTP。
- 原policy.json保持schema=mairui-shared/v1、当次唯一出口、逐licence_id正整数per_minute_limit；不得提高既有档位/管理员限制。产品取文件和数据库上限的较小值。

合成结构（不是授权）：
```json
{"schema":"mairui-shared/v1","egress_ip":"192.0.2.10","licences":{"00000000-0000-4000-8000-000000000099":{"per_minute_limit":150}}}
```

## 发送与停机必须走同一临界区

- 永久send-control.lock使用同一POSIX flock inode，无TTL。四种真实发送、write_stop以及全局暂停写入方都持它完成检查和动作；不得删除/替换该文件，等待者会校验私有文件权限。
- 全部业务检查、最终STOP/Redis检查和实际HTTP在发送临界区内；同线程试图在发送内重入写停机直接拒绝，其他线程/进程的写入必须等待当前HTTP完成。写入方先取得锁时，后来的发送检查拒绝，0 HTTP；发送先取得锁时，写入无法插到检查与HTTP之间。
- 支持的操作入口是同版容器/探针环境的`python -m app.cli.ingest_control --stop`或`--pause`。恢复全局暂停需Chief当次明确授权后才执行`--resume-authorized`；该参数不会清公共STOP或证书halt。
- 全局暂停先持锁写入/fsync共享PAUSED镜像，再写Redis暂停键；恢复先成功删Redis键，再删镜像。失败保持停机。探针同样读PAUSED，因此无需在探针环境装入Redis凭据。
- 禁止绕过入口直接Redis SET/DEL暂停键或直接touch/覆盖STOP；这些写法不参与互斥，不能作为已接齐同步写入方的验收。旧运维脚本若有此操作须先改入口；仓库当前没有其他生产暂停写入实现。
- 进程崩溃虽由内核释放flock，原single-egress.lease.json及未知在途预留仍保留，不能借锁释放自动续跑。管理员本人证书暂停/替换/DELETE还受原用户级PG事务锁保护。
- 公共STOP与PAUSED停全部证书；历史STOP仍在入口、等待每≤0.25秒及发送前映射，合法目标才算存在，失效软链/异常哨兵闭锁；固定脱敏内容flush/fsync，不复制旧STOP。

## R3A：证书作用域、删除与保留期

- 关联tag用独立0600运行时binding-key.json做带用户域的HMAC；不读原DB证书HMAC/APP_MASTER_KEY，不产生证书派生文件名。tag只存数据库私有行，本地SQLite绑定缓存已移除。
- 活跃关联不靠本机TTL使有效halt失效。DELETE/替换与关联保留变更在同一数据库事务提交：非冷却即删；冷却到paused_until，空截止最多删除后24小时。回滚也一起回滚；清理和读取判定只用数据库now()。ingest每次心跳都清理到期tag，即使replay、全局暂停或未挂共享目录也执行数据库清理，不因此放行发送。
- scope历史仅含随机UUID、原licence UUID与detached_at，不含tag/证书；关联清除后立即detached，原state-<scope>.halt.json及审计/批次事实保留，但已知detached的103/429不进入其他证书执行门禁。
- 同一用户冷却期内重提相同证书可恢复原scope/halt；不同证书/其他用户/过期tombstone不继承。已删除原licence_id本身不可再外呼。未删除有效关联上的103/429仍须原R3授权双侧解闩，显示暂停到期不会自动清halt。
- 无法在scope历史证明归属的旧UUID halt、未知state-scope halt保持全局停机，由授权运维另单归档/绑定；公共STOP不随关联清理失效。旧.binding.json、certificate-*或SQLite缓存存在时仍拒发，不自动猜测迁移。
- 未知在途和遗孤最近一分钟请求账继续保守闭锁，不删除预算/原128台账来放行。同证书有效关联期间仍共用分钟账与单出口租约。

## 授权与预算不扩展

- ingest仍禁止全站MAIRUI_LICENCE/APP_MASTER_KEY；产品仅从本人HPKE vault临时解封。探针证书仍只按当次授权安全接入，不打印或持久化。
- 名单仅已覆盖交易日北京时间18:00至23:59:59，固定三HTTP、各端点一次、完成到下次开始≥60秒，无重试、不跨日补打；探针优先避让与同一租约不变。
- 验证独立root-owned只读回执/run/aia/authorizations/mairui-verification.json：本人user_id/licence_id、唯一receipt_id、带时区起止、max_http_requests=1，期限正数且≤30天。仅名单三次授权不会顺带验证，不占探针128。
- 验证每证书v2 consumer group保留原流，v1旧pending不删；每tick最多处理20条，所领消息逐条处理/确认，跳过他证书历史，自己的pending立即重查，不再一条一tick或逐条等一分钟。原意图/回执持久去重防重复HTTP。
- T-B05出口确认、T-B86官方证据/分项128台账/临时证书0600及清理均保留。站内通知/SSE继续原去重与四字段，不新增外发。

申请新任务：由Chief安排RV-09、0029/私有角色与探针DB参考/统一写入入口的运维接线验收；本单未部署或实跑。
