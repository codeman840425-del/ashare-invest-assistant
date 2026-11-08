> 2026-11-08 14:02:02 北京时间（UTC+8） 更正：当前3必需HTTP与每日1次限制冲突，代码已全入口live闭锁；下述ACL足够不代表次数授权/上线通过，安装回执不能解除。须先编排者/架构师裁定来源完整性与HTTP预算。

# T-B90 最小操作清单（北京时间 2026-11-08；仅隔离库演练）
基线34c88c3；未改deploy/grants/CI，无生产/用户库连接，未读取真实DSN/密钥。
运行身份按已有worker=aia_api、ingest=aia_ingest；隔离连接核对session_user/current_user，非superuser/bypassrls。
原deploy/db/roles/grants.sql仅替换psql密码占位为NULL在独立无网络PG执行，未补授任何权限。
## beat/worker（演练均以aia_api连接）
- market.trading_calendar：SELECT，交易日/覆盖范围判定。
- app.user_data_licence_status：SELECT；app.user_data_licence_holds：SELECT(user_id)，本人证书可用/暂停/归属；不能SELECT底表ciphertext。
- market.master_runs：SELECT/INSERT/UPDATE(status,finished_at,stats,snapshot_ids)，先落日意图、回放、成功/失败与逐接口预留账；master_runs_id_seq USAGE。
- market.master_vendor_batches：SELECT/INSERT/UPDATE(status,reconciled_at)，唯一日批次与最终应用状态；UUID无sequence。
- market.master_vendor_list_rows：SELECT，读取ingest归一名单；不需新增写权。
- market.securities：SELECT/UPDATE(risk_flag,listing_status,field_sources)，仅已有证券F14/F15更新，不新建/复活/批量清空。
- market.master_snapshots：SELECT/INSERT/UPDATE(parse_status,reject_reason)；master_snapshots_id_seq USAGE，追溯/拒收记录。
- market.security_risk_flag_history、market.security_listing_status_history：SELECT/INSERT/UPDATE(valid_until)，双表PIT半开区间；无sequence。
- app.notifications：SELECT(user_id,read_at)，认证本人未读聚合；登录本有users/会话权限不新增。
## ingest（aia_ingest）
- app.user_data_licences：SELECT(id,user_id,ciphertext,seal_key_version)，仅已绑定可用证书的HPKE解封；status视图/holds同上；market.securities SELECT(code)。
- market.master_runs：SELECT/UPDATE(stats)，持久预留后发送、103/429永久停止标志；无INSERT/sequence。
- market.master_vendor_batches：SELECT及既有列级UPDATE(status,fetched_at,datasets,error_code)；market.master_vendor_list_rows：仅INSERT，无SELECT/UPDATE/DELETE。
实证：同一真实Redis流→aia_ingest查询/HPKE→行INSERT→aia_api应用双history；API读ciphertext与ingest读vendor行均被PG拒绝；既有ACL对本链足够，无新增授权缺口。现存ACL较最小清单更宽，不在本任务缩改。
部署前：编排者核实本人日常实际授权；运维核对实际角色/目标head0023和原ACL、安装root属主0444非secret回执（/run/aia/authorizations/mairui-daily.json，父目录不可由应用写、只读挂载），使用既有HPKE密钥挂载。不得客户端自报批准。
运维准备ingest可写持久运行目录(/run/aia：daily.tmp独占0600、HALTED)与STOP路径(src/backend/probes/results/STOP)、worker快照共享卷，单出口单ingest；没有安装/启用任何真实回执或调度。103/429另落DB halt，无自动解除入口。
边界：首次实采/真实鉴权/生产授权均未验收；外部HTTP已发送但结果未提交的崩溃记uncertain并失败，不重试、不伪装exactly-once或补采。
