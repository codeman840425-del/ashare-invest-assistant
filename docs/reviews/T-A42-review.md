# T-A42｜定点复审
时间：2026-11-08，北京时间（Asia/Shanghai）；仅审 0289388、d5a9a60 的 diff 与指定证据；本机例外，无 push/DeepSeek/服务操作。
结论：0289388 通过（静态修复范围，N-I1/N-S1/N-S2关闭）；d5a9a60 不通过完整收口（T-A35 I1授权仍待落地），未发现新增阻断。
路径简写：B=src/backend/；E=B/app/intraday/engine.py；M=B/migrations/versions/；测试文件均在 B/selfchecks/。
- N-I1 关闭：B/app/plans/generation.py:358-374 改合法 warning 并经 RiskFlag 校验；test_tb91_closing.py:480-488 全旗标校验（后端）。
- N-S1 关闭：test_tb91_closing.py:209,310-419 为 buy/add 补实际POST 503、budget_plan_amount及八表前后不变，并验证他人拒绝和 sell/reduce 不受预算unknown门控（后端）。
- N-S2 关闭：generation.py:300,363-368 区分无止损无法计算与有止损不监测；test_tb91_closing.py:503-519 校验已有止损保留正确loss且无矛盾gap/文案（后端）。
- T-A34① 关闭（代码/离线范围）：E:457-507 按本人、版本、scope、账户、参数匹配，created_at,id排序（后端）。
- T-A34② 关闭：E:510-514,590-604 优先已产候选实例，否则首实例，空集null；冻结入表，B/app/intraday/events.py:38-80 读冻结值（后端）。
- T-A34③ 关闭：E:599 冻结同序前20个instance_ids；events.py:66 返回存档数组，不随暂停重算（后端）。
- T-A34④ 关闭：E:621-642 一次归档 rows+carried；B/app/suggestions/service.py:102-198,240-245 校验本人当前不可变旧档、哈希与结论逐字一致，不以沿用标记绕过验证（后端）。
- T-A34⑤ 关闭：E:536-545 冻结表幂等防重、:644-659 只append一次且ref=signal/event.id；既有notify/service.py新ref才增计数/版本逻辑未改（后端）。
- T-A34⑥ 关闭：E:650 仅invalidation→important，其余attention，不按实例数升级（后端）。
- T-A35 B1 关闭（静态）：M/0025_p2n06_notification_merge.py:227-321,323-390 保存原行/新增列并恢复，旧键碰撞条件拒绝；0026:13-15,34 保留引用表改名、再升恢复，不再drop refs或固定抛错（后端；维护窗口动态复验待运维）。
- T-A35 I1 **部分关闭**：M/0027_tb92_frozen_projections.py:110-121 按source_licence_id修复shared归属；B/app/cli/delete_user_data.py:245,384,487-497 补新表/触发器清单；但deploy/db/roles/grants.sql未改，aia_maint原有表/列授权缺口及新投影表授权只在隔离selfcheck delta中补，正式最小ACL未交付应用（运维落地，后端协调）。
- T-A35 I2 关闭：B/app/api/v1/notifications.py:179-235 在retry、reset、每条首次补读、实时帧及心跳前复查会话/approved用户；不是仅检查实时循环（后端）。
- T-A38 Part0 不猜归属/unknown隔离：关闭；0025:236-304 只接受显式原始snapshot引用并校验本人证书、证券、时点、正文hash，无证继续拒迁；缺历史实例绑定置unknown；0027:59-64 对旧布局无冻结回执事件标unknown，events.py:17-31 仅展示有冻结投影的事件（后端）。
- T-A38 Part0 可逆回退：关闭（静态）；0025:323-390 旧键检查后保存完整事实，0026/0027:132-138 改名保留refs/冻结表；升回恢复，拒绝静默合并旧键冲突，不把“拒迁”和“无法降级”混为一谈（后端）。
新增阻断0；权限缺口是旧I1未完全关闭，不重复计新问题；修改既有0025/0026的特批见T-B92-evidence.md:3，其余无deploy/tests/docs越权改动。
定点命令：在B下 PYTHONPATH=. uv run pytest -q，选择test_tb91_closing.py的 test_actual_buy_add_null_budget_to_confirmation_and_number、test_budget_exhausted_reason_commit_and_recheck、test_budget_multi_full_allocation_latest_unknown_and_stale 及两个test_rc1_disabled*节点。
结果：原4个失败节点已重试；multi现扩为buy/add，连同2个警示回归共7节点，全部setup ERROR，专用PG socket /tmp/tb70-tb91-owned-socket/.s.PGSQL.5432 仍Connection refused；0项进入业务断言，不记作断言失败或通过。
未起/改服务、未改连其他库；T-B92-evidence.md:12-19 的历史10节点通过仅为交付方历史证据，本轮未复跑其PG集成链，不能代替本轮动态验收或生产放行。
提交前：本文secret_scan files模式、git diff --check通过；仅pathspec本地提交本文，不触碰其他角色WIP。
申请新任务：请派运维补齐I1最小ACL并恢复专用测试PG，再派定点复验。
