# T-A41｜T-B91追加修复（非生产签收）
时间：2026-11-08T18:06:43.986893+08:00 北京时间；本地提交 0289388d811db051931fa0db08cdb516d1204cb0，未推送。
N-I1：RC1关闭警示改既有warning，经共享RiskFlag完整验证后持久化；未改枚举/放宽模型。
N-S2：有止损仍计算亏损，仅提示不主动监测，无假max_loss_amount gap；缺止损才null+gap及无法计算警示。
N-S1：buy/add在真实本人unknown预算状态POST503+budget_plan_amount；草案/计划/版本/候选/状态事件/原因/快照/审计8类事实完全不变；他人400不写。
退出边界：追加另一指定标的688073合成持仓与可信报价，实际确定性引擎候选→sell/reduce草案POST201；未误加买入预算门禁，未跳过反向计划保护。
测试：8个唯一直接节点分组最终通过，包含架构师原4个PG失败参数节点；首轮3个新增夹具/精度断言失败已修，另一次收集导入错误均不算通过。
检查：两改动文件ruff、mypy、diff通过；暂存秘密扫描2文件阻断0/警告0；无全量/coverage。
环境核验：前轮38fc560已按要求删除专用PG/Redis，旧socket Connection refused不算业务通过；本轮另起无网络PG16/Redis、无TCP，以aia_api跑真实API/DB。
复现：reports/T-A41-reproduce.md含专用启动、fixture真实迁移至head0026、原节点/新增节点与清理命令及非秘密参数。
清理：临时测试库剩余0；仅本轮PG/Redis已按完整ID优雅停止并删除匿名卷，B92及他人原服务未动。
DeepSeek：复用reports/deepseek/T-B91/已复核24条纯合成操作数作有止损夹具；本轮0外部调用，元数据reports/deepseek/T-A41/，无源码/秘密外发。
改动仅src/backend/app/plans/generation.py、selfchecks/test_tb91_closing.py；无迁移/配置/前端修改。
遗留B2：生产采集完成→owned_quote调用接线仍缺，按评审保留原阻断；需编排者另派，不把离线手动注入算生产链。
边界：0麦蕊/官网/真实凭据/私密样本/正式G7/真实提醒/生产调度；全部身份、账户、持仓、行情仅合成隔离。
B92：自身8文件WIP与SHA清单完整保留于/workspace/tb92-wip-preserved-20261108/，未混提交；恢复前核对基线以保护他人后续变更。
申请新任务：请恢复T-B92；后续P2N-08→P2N-09，T-B90b/B86仍挂起，等待明确恢复。
