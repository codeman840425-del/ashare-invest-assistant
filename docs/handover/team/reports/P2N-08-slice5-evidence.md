# P2N-08最后切片5：真实PIT读源/评价部分交付
最近绿色49c6c796c915fb2756910ca2625fbbb093e45605，本地未推送。没有完整覆盖来源定义，因此不交伪正常/伪触发闭环。
## 四路径
- app/feedback/plan_source.py：SQL只读且最小列，不读原始导入行、<account-field>hash/掩码、资金金额或密码。先校验approved本人/未归档同属账户及created<=as_of；计划按owner/account/code，版本仅created<=as_of，qty只取completeness.qty。
- 关闭只认既有actor_id=owner/target_type=action_plan/plan.closed审计at；当前head/current_version_id/updated_at不能提供历史截止。缺关闭证据、缺版本号序列、空/冲突区间均gap，不从状态猜截止。后来的版本/关闭不得倒灌。
- 成交按owner/account/code和created过滤，traded_at或date→15:00；voided_at在as_of之后仍保留原成交，在as_of之前则标作废；替代行按自身created_at可见。导入批次必须同owner/account、有committed_at且不晚于as_of。
- app/risk/evaluation.py：现有inputs真实调用加载器，附只读来源证据/gap到绑定一致的assessed，再复用current；不得把错绑证据给另一owner。缺覆盖仍unknown，current最早时点与源证据一致，无任何新增HTTP写接口。
- selfchecks/test_p2n08_plan_source.py 两个真实PG节点；既有test_p2n08_plans.py只给一个受影响适配节点补错绑证据不泄漏断言。
## 真实阻塞，不可绕过
契约T-A33定义累计/区间，却未定义如何证明历史成交/计划覆盖完整及覆盖起止/捕获水位、导入批次完整范围。当前accounts/trades/import_batches/plan_versions无此合同列或已验证标记。不能把committed、非空、余额、用户JSON summary或completeness自报当完整。
加载器固定不签署未经证明的覆盖：Facts.coverage_at=None、coverage_complete=False，plan_history_coverage_unproven；核心因此unknown且不出flag。不是全链完成，需架构师定义可信证据来源及生产者，再做可审计持久化/读取；本片不擅加schema/迁移。
## 3唯一定点与复现
cwd=src/backend，PYTHONPATH=.；venv=/tmp/rv7-backend-venv。
pytest -q selfchecks/test_p2n08_plan_source.py：2过（/tmp/p2n08-s5-source.log）。实际aia_api且非superuser，真实Alembic head0027、原deploy grants隔离加载，root仅纯合成种子。
节点1：版本9:59仅旧版、10:00同刻归新版；旧两笔60+60=120，10:10冲正后60+40=100，旧void不提前应用、替代记录不提前可见；没有覆盖凭证时仍unknown。current同参数两次完全一致、最早as_of=09:00，SQL捕获无INSERT/UPDATE/DELETE，事件/快照/通知计数不变。
节点2：当前done及updated_at19:00不使16:30关闭提前影响16:00；17:01读取真实16:30审计截止；未来17:00导入此前不见；他人行不读、他人账户返回无facts/无evidence；无审计关闭只有gap。JSON伪coverage_complete不生效。
pytest -q selfchecks/test_p2n08_plans.py::test_existing_evaluation_adapter_bindings_disabled_and_partial_not_ok：1过（/tmp/p2n08-s5-binding.log），错绑时源证据不泄漏，未重跑整个14/42组。
mypy --follow-imports=silent仅app/feedback/plan_source.py、app/risk/evaluation.py通过；ruff仅4变动路径，diff通过；secret_scan staged四路径阻断0/警告0；无全量/coverage。portfolio既有distinct弃用警告未扩修。
## 隔离资源复现与清理
mkdir -p /tmp/p2n08-s5-owned/pg && chmod 777 /tmp/p2n08-s5-owned/pg（仅本片无凭据socket目录）。
docker run -d --pull never --name p2n08-s5-owned-pg --network none -e POSTGRES_HOST_AUTH_METHOD=trust -v /tmp/p2n08-s5-owned/p<path> timescale/timescaledb:2.31.0-pg16 -c listen_addresses=''。
测试模块fixture只允许AF_UNIX、socket=/tmp/p2n08-s5-owned/pg；复用随机tb70_p2n08s2_<uuid>库，真实upgrade head、读取原grants以NULL替代密码占位，不取任何真实凭据。每节点清理自己的随机库。
完成后按创建记录完整CID核对名称，只stop/rm -v本片PG；确认无随机测试库后清本片空socket/父目录。无Redis创建，无活动隔离资源遗留；旧切片2 uid70空目录未提权处理。
本片仅需已有aia_api SELECT：app.accounts/users/action_plans/plan_versions/audit_logs/trades/import_batches；current既有读表另沿原授权。实际角色已运行，不新增grants，不改deploy或共享/生产库。无新表/列，aia_maint无本片新增权限需求。
DeepSeek：本片未采用已有24算术操作数，它们不适配实际DB归属/关闭审计/覆盖证明的PIT安全验收；本片沿用已有本地合成夹具并按golden/合同独立核验，未新增调用，未发源码/秘密/真实数据。前片的已审草稿使用见各片证据，不虚称本片使用。无Mairui/官网/证书/资金/G7/真人通知/生产作业。
最后切片已交付后收口；全部剩余入口见P2N-08-handoff.md，不自行启动新片/09。
