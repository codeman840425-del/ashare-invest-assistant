# T-A35｜P2N-06 后端评审

## 范围与结论
- 目标：`be685b1d1257329cb675aa124b813e2c90dea676`，并核对依赖迁移 0024；行号基准为评审时 HEAD `93df55ab1f789ca7b7b5321dec740cd80ab6c34d`。通知/盘中/0025–0026 相关目标文件与该提交相比无后续差异；不评价其他人的未提交修复。
- 本地提交的远程包含查询为空；依赖本机未推送内容，本次不克隆、不推送、不访问用户电脑。
- 依据：契约 §7.11.4（T-A28、T-A31、T-A31b、T-A34）及 §8 reset，plan §0A.3、§2.6、§7.3；交付说明 `/workspace/team/reports/P2N-06.md`、权限说明 `P2N-06-worker-grants.md`。
- **结论：不通过发布验收；阻断 1、重要 2、建议 0。** 离线通知/SSE 主体静态可接受，但迁移回滚、注销权限闭环及补读期间的会话撤销仍须修复。
- T-A34 多实例 instance_id/instance_ids、一次归档/通知与按事件 merged_count 去重由 T-B92 修正，本次列为已知、不计缺陷。

## 阻断
### B1 0025 无条件禁止 downgrade，0026 回退直接丢引用事实（后端）
- 位置：`src/backend/migrations/versions/0025_p2n06_notification_merge.py:156–157`；`src/backend/migrations/versions/0026_p2n06_notification_refs.py:30–31`。
- 0025 的 downgrade 即使空库也固定抛 RuntimeError，因此 `0026 → 0024` 无法完成；先降至 0025 会先 DROP notification_refs，若其后 0025 报错且整体迁移未按单一事务执行，可能停在已丢引用的中间态。即使单独成功降至 0025，再升至 0026 也只建空子表，API 投影不再读取旧 JSON refs。
- 要求：本任务明确要求 0024–0026 可回滚且带数据安全；T-A28 中通知行和引用是事实来源，不能把“拒绝回滚”表述成“回滚已验收”。0025 拒绝猜历史事件归属是正确的升级保护，但不是 downgrade 实现。
- 修复：提供可执行、保留通知及引用事实的回退/再升级方案；新归属键撤除前检查旧唯一键冲突并显式处理，不静默合并或丢事件。若确需不可逆迁移，应由用户另行批准备份恢复替代方案，当前不能自行豁免可回滚门槛。
- 验收：空库与合成带数据库分别执行 0023→0026→0024→0026，核对通知正文/已读/version/全部 refs 与行数；模拟回退失败验证无半完成状态。不得对共享业务库执行。

## 重要
### I1 新增引用表及证书归属未同步维护角色与删除保护（后端，协调运维授权）
- 位置：`src/backend/app/cli/delete_user_data.py:182–186,241–245,255–268`；`deploy/db/roles/grants.sql:238–406`；`src/backend/migrations/versions/0013_t_b16_core_r2.py:42–55,262–299`。
- 本提交新增 DELETE notification_refs / intraday_candidate_refs / signal_states / intraday_universe，且 signal_events 删除谓词新增 source_licence_id；现有 aia_maint 按列白名单没有前四表所需授权，也没有 signal_events.source_licence_id SELECT。默认授权只给 aia_api/ingest，不会自动补 aia_maint。SQL 解析检查权限，即使相应表为空也会失败。
- 另外新生成的共享事件 `intraday/engine.py:439` 为 scope=shared、user_id 为空；purge_row_owner 仍将 signal_events 列为直接 user_id 归属，未按 source_licence_id 解析。补齐 ACL 后，旧不可变触发器仍会拒绝删除这些本人证书派生事件（0011 的 purge_permits 对 DELETE 要求 purge_row_owner 命中待删用户）。
- 契约/plan 要求：只允许本人证书/本人事件，plan §7.3 同时要求注销物理删除本人派生事件与通知，不能上线后将注销破坏，也不能用库属主绕过维护角色。
- 修复：追加迁移更新删除归属函数，按证书 FK 解析 shared 事件所有人，保留非本人拒删；同步维护角色最小表/列权限与自检清单，worker 仍用 aia_api，仅需新增 refs 表 SELECT/INSERT，不借此扩大维护角色/业务角色权限。
- 验收：以实际 aia_maint 跑空表及带合成 shared/user 事件、引用的删除事务；本人派生数据全删、他人数据保留；非维护角色不可借 purge 通道删不可变事实。此项是静态确定的授权/保护遗漏，本次未连接数据库或实际删除。

### I2 首次续传补读期间不再检查会话，撤销后仍能发送整批缓存（后端）
- 位置：`src/backend/app/api/v1/notifications.py:179–207`，尤其 `:193–196` 与 `:199–207`。
- AuthDep 只在进入路由时鉴权；initial replay 数组随后逐条 yield，直到整批发送完才进入检查 session/user 的 while。若客户端在第一条补读后退出登录/被禁用，剩余补读仍全部发送，缓存量大或慢读客户端会延长失效后的继续推送时间。
- 要求：本任务的“会话失效停流”同样覆盖续传数据，不能只检查实时轮询；本人隔离没有发现串用户，但撤销边界未完整覆盖。
- 修复：把会话/用户有效性检查复用到控制事件与每次补读发送之前（至少每个有界批次检查），失效即结束；实时循环检查保留，不因请求开始时通过鉴权而豁免补读。
- 验收：建立含多条补读事件的真实 HTTP/ASGI 流，读第一条后撤销会话或禁用用户，断言后续业务帧不再发送；无效首连仍按原认证错误响应。

## 已核对、未新增问题
- 隔离：notifications 列表/计数/read/read-all 皆以 auth.user_id 限定，他人 read 返回 404；`intraday/events.owned:20–31` 将来源证书 user_id 与 shared/user scope 同时过滤。未发现客户端可指定他人的 owner。
- SSE namespace：`notify/transport.py:35–83` 所有 seq/order/body/dedup 键均为 `p2n06:sse:<user>:…`；seq 不设 TTL，Lua INCR 后以十进制事件 id 写入，补读按该用户 id 排序，只取当前 600s；没有跨用户读取缓冲。
- reset：`notifications.py:181–193` 首发 retry:3000；`transport.reset_reason:136–146` 对非 ASCII 十进制/非法序号/超当前返回 unknown，无锚点或超窗返回 expired；reset 带 reason/latest_event_id，不带 Last-Event-ID 不 reset，之后继续实时流。无历史事件时 latest_event_id=null。
- 通知：`notify/service.py:83–162` 使用北京时间固定 10 分钟桶；现有 `(user_id,dedup_key)` 唯一约束配合同 key 事务 advisory lock 实现并发安全的查找/插入/更新语义，不能仅因未使用单条 ON CONFLICT UPDATE 就认定竞态。refs 独立 PK、版本与正文/未读重置同事务；最大 severity、最新 target/title/body、refs 按 at desc 最多20条符合要求。
- 已读：`notifications.py:129–159` 仅 read_at 为 null 的行更新并 version+1；重复标读与重复 ref 不增版本。新事件重置未读但不新增同桶行。旧通知投影由 `service.project:36–58` 回退 merged_count=1、version=1、updated_at=created_at、refs=[]。
- cadence：`notifications.py:56–88` 完成 API 1min/3min/5min 与 DB 1m/3m/5m 映射；`transport.enqueue/flush:86–133` 按整 N 分钟结束推最新完整通知，important 立即；signal 等 publish 路径不受 notification cadence 限制。待推队列先 claim 后推送的丢失属于契约允许的临时缓冲丢失，不报持久化缺陷。
- 迁移升级：0024→0025→0026 串联，AST 静态检查唯一 head=0026；0025 旧 signal_events 非空明确拒迁，不猜归属；只清可重建 signal_states/universe 并告警，不删除旧通知；证书 FK 指向 app.user_data_licences.id。未实际跑带数据升级，交付说明的历史通过记录不是本次动态验证。
- 角色：部署 worker 使用 aia_api；其既有 DML/default privileges 静态覆盖新表业务操作。新增表没有序列；实际生产 ACL 未连接核查。I1 的维护权限遗漏不能被“worker ACL 足够”掩盖。
- 外部边界：consumer/compute/handoff 生产闭锁、仅 test+物理隔离证据入口，未将此离线交付视为已完成生产行情总装；本次未发任何麦蕊/官网/邮件/聊天/外部提醒，也未读取真实密钥或样本。

## 本次验证
- 定点 ruff（notifications/signal_events API、intraday、notify、相关表、0024–0026、自检文件）通过；未检查或改动其他人的 WIP。
- Python AST 静态核验迁移链与单一 head；未运行 Alembic、数据库升级/回退、pytest、全量测试或 coverage。
- 提交前对本评审文档运行指定 files 模式 secret_scan，要求阻断0，再运行 `git diff --check -- docs`；仅本地 pathspec 提交。

DeepSeek：未用，原因 评审结论禁止外包。
申请新任务：后端修复回滚、维护删除闭环及补读撤销后，定点复审；多实例问题继续由T-B92负责。
