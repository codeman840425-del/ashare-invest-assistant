# T-B92 定点证据与最小运维授权（本机离线，不是生产验收）
## 实现及保留事实
- 依据T-A34 f811992、T-A35 25efe5a、T-A38 c45b7b9；仅特批修改0025/0026，新增0027，0021及其他旧迁移未动。
- 当前归属/账户/版本/参数/可运行实例按created_at,id升序匹配；优先首个已生成候选实例，否则匹配集首个，空集才null；instance_ids冻结前20个。历史无完整集合证据不猜成空集。
- 同一用户/事件在事务内只冻结一次；真实P1生成的所有匹配结论合为一次归档/原始事件ref。后续其他版本事件逐字沿用未受影响结论，绑定当前本人不可变归档快照及hash；旧实例暂停不重新解释历史，但旧候选的当前阻断仍保留。篡改结论或使用他人归档不能借沿用标记绕验证。
- 0025只承认原始detail显式snapshot引用，核对purpose、快照/证书所有人、时间、证券代码及正文SHA256；缺证拒迁且事务回滚，绝不删除旧事件。旧实例绑定unknown排除新投影；不补通知、不造ref、不改已读/计数。
- 0025降级先保存完整原行/新增列至app.p2n06_rollback_0025并保留候选refs；0026/0027把refs/冻结投影改名为*_rollback保留。再升级恢复，旧事实逐行JSON相同。旧键发生真实碰撞则条件拒绝降级并保持head/事实，不是无条件拒绝。
- 回退仅维护窗口使用，必须停新旧业务进程；保留表仅迁移所有者访问，不能在旧runtime继续写事实。未知归属须运维先隔离存档，不许靠清表解除阻塞。
- 兼容已经部署的原版0026：0027增补unknown标志/部分唯一索引，不要求重复运行0025，不删除既有候选/通知关系。
- shared删除归属由source_licence_id→本人决定；无purging状态、他人purging或伪造GUC均不能删除。注销CLI显式登记新表外键及已审核触发器。
- 首次SSE补读的retry/reset/每帧及心跳都复验真实SessionStore与用户状态；撤销后停止剩余缓存，不借缓存续发。
## 定向测试（唯一10节点，分批最终通过；无全量/coverage）
入口：src/backend/selfchecks/test_tb92_repairs.py。两个SSE参数、三个选择器边界均按唯一节点计数。
1. 合法旧0023非空事件/已读通知→0024→0027，24个真实服务ref→0024→0027，逐行比较快照/事件/候选/状态/通知/refs/冻结投影，检查外键和唯一head。
2. 无明确历史来源的旧事件拒迁，旧行、版本均保留。
3. 实际aia_api非超级角色：24实例经真实worker/DSL/P1/Redis/PG归为1建议/1ref；暂停后投影不变；后续独立版本事件沿用旧24条并增加1条，2建议/2ref；重放不增量。读后新ref按契约重置已读并增version；跨用户投影与篡改沿用证据拒绝。
4. 同一整链全部带数据降级再升，维护角色原样deploy grants加下列收窄delta，实际注销删除2个shared事件及所属新关系；他人用户保留。假模板在fixture起始设为公共虚构模板，不绕过既有“本人创作策略阻断注销”规则。
5. 实际HTTP/SSE在retry后/首帧后撤销Redis会话，剩余缓存不发送；三个选择器边界；旧键碰撞原子拒绝；原版0026布局带通知ref升级保留事实。
最终相关日志：/tmp/tb92-final-targeted.log（8通过，两个新增夹具问题）；/tmp/tb92-two-final.log（修正为合法夹具后2通过）；/tmp/tb92-roleproof.log（强化实际角色/收窄权限后整链复验）。不把早期失败日志当通过。
类型：mypy --follow-imports=silent仅11个任务生产文件通过；默认跟随导入会报5个既存外域文件的6项错误，未越权修改或宣称全仓类型通过。相关ruff/diff检查通过。
## 运维最小ACL清单（只隔离演练，未改deploy/生产授权）
- 新app.signal_event_projections：aia_api SELECT,INSERT；撤回UPDATE/DELETE；aia_ingest全部撤回。aia_maint SELECT(user_id),DELETE。UUID主键无新增sequence授权。
- aia_maint新增/缺口：app.notification_refs SELECT(notification_id),DELETE；app.intraday_candidate_refs SELECT(instance_id),DELETE；app.signal_states SELECT(id,source_licence_id),DELETE；app.intraday_universe SELECT(source_licence_id),DELETE；app.signal_events新增SELECT(source_licence_id)，DELETE沿原授权。
- 既存依赖缺口：CLI动态统计market.master_vendor_batches时原样grants拒绝SELECT；需要aia_maint SELECT(source_licence_id),DELETE，删除本人授权源批次。其明细FK级联无需独立新增sequence/表权限。本任务未实现或修改暂停的T-B61队列。
- T-A38五表矩阵隔离演练：aia_ingest五表全部撤回SIUD；notification_refs/intraday_candidate_refs/signal_events的aia_api仅SI；signal_states仅SI及UPDATE(last_tick_id,rule_states,state,changed_at)；intraday_universe仅INSERT、UPDATE(computed_at)、SELECT(trade_date,source_licence_id,security_code,computed_at)。不得默认全表U/D或ingest继承授权。
- 操作完整SQL在本任务selfcheck grants()，只可由运维审核后应用；实际生产现状未连接核验。0025保留事实表不授予worker/ingest/maint读取权限。
## 边界
0真实采集/证书/私密/真实通知/生产库/G7/调度操作；B90b/B86挂起不动。B2真实分钟行情采集完成后的生产调用接线仍缺，不扩大修复、不宣称生产闭环。隔离删除的是虚构用户，未对任何真实身份运行注销。
DeepSeek：复用reports/deepseek/T-B92/已审24条纯合成时钟/分组操作数，保存为selfchecks/fixtures/tb92_operands.json；17:31北京时间草稿；规则/代码/断言/安全由本地定稿，无私有源码/秘密/业务数据外发。
