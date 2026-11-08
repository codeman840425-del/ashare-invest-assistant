# T-A43｜运维ACL与收口脚本静态复审
时间：2026-11-08 MST；输入5a26d17及条件候选afccd5e；结论：**不通过本次“与T-A38逐列一致”验收**，阻断项1（口径/授权差异，非新发现串用户漏洞）。
阻断项B1（运维，架构协调）：deploy/db/roles/grants.sql:1064 给aia_maint增加signal_states.id的SELECT；T-A38 Part0表只列source_licence_id。本轮只读有效ACL校验393项，唯一不符正是此额外列；其余392项匹配。
该id授权有后续T-B92-evidence.md:23的依赖依据，不宜直接撤掉破坏CLI；须先明确批准并同步T-A38矩阵，或调整实现恢复原矩阵，不能同时声称“原表逐列一致”。
五表aia_ingest有效SIUD全无；aia_api的S/I及state四列U、universe四列S与computed_at U均吻合；aia_maint其余四表及state其余操作/列吻合，无多授（按全部现有列逐项检查，含角色继承/PUBLIC的有效权限）。
共享归属保护已在候选落地：src/backend/migrations/versions/0027_tb92_frozen_projections.py:110-121 按source_licence_id→本人，user scope冲突返回null；隔离库现行函数含此逻辑且signal_events不可变触发器enabled=O。
T-A35 I1：归属函数和原缺失ACL已落实候选/隔离库；但按本次严格矩阵门槛尚不能写“完全关闭”，先解除B1；本次未做真实用户删除或生产授权。
部署脚本仅静态读5a26d17版本：deploy/scripts/closeout.sh:438-441 对缺省/非精确1的DEPLOY拒绝；:451-452 自检内部强制SELF_CHECK=1，继承DEPLOY=1仍由独立闸门拒绝。
self-check模拟步骤仅SIMULATE=1跳过；缺省或拼错模拟值时SELF_CHECK闸门先拒绝deploy；run_backup/run_up/verify_in_db_roles另有SELF_CHECK拒绝，未发现自检绕到真实部署路径（:416-435）。
真实deploy后的verify已改为compose db-roles容器内执行（:430-446），非宿主默认verify；失败即停，不再跑nginx/HTTP。未知模式直接die（:593-603），未发现拼错命令回落deploy。
rehearse-db缺省/模拟值拼错会走start_iso，而不是沿用外部PGHOST：:258-269固定新socket、direct模式及临时库，容器network none；这仍会创建隔离资源，本轮没有执行。
O1清单修复：accepted.manifest:9-24分开角色/来源，明确旧不通过评审只是文档、R09用后续版本、交接仍草稿；未把全量main历史默认设为验收集合。
O2/O3清单修复：manifest:25-31区分4ccc859历史快照、c2353bf旧交付、175b98e基线与afccd5e条件候选；d5a9a60/0027不进正式MERGE，B1维护窗口复验仍待，不把拒迁/无冲突当验收。
ACL测试：只读连接专用Unix socket的t_o33_acl，确认listen_addresses为空；393项有效表/列SIUD断言392匹配、1差异，差异见B1；未执行apply-roles/verify-roles/closeout脚本。
后端抽测：在/workspace/wt-review-T-O33/src/backend以原夹具/no_network运行test_tb91_closing.py的budget_multi_full_allocation_latest_unknown_and_stale[buy]、rc1_disabled_with_stop_keeps_loss_and_valid_warning[disabled_with_stop]，**2 passed**。
后端夹具仅使用其自建合成临时库及固定PG/Redis Unix socket；未自行起/改服务，未访问口令目录、真实主机或部署开关；脚本安全结论仅为静态结论，不冒充运行自检。
本文提交前secret_scan files与diff --check通过；仅pathspec本地提交本文，不push，不调用DeepSeek。
申请新任务：请确认state.id后续最小依赖是否正式修订T-A38矩阵，再派收口。
