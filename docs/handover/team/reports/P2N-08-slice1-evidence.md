# P2N-08 切片1证据（非整项验收）
依据：T-A33 462057c、T-A36 78cd872、T-A37 3b36b74，当前契约§7.11.3及plan§2.5.7/2.8.2。后续插队明确只先交RC5/健康核心，不混入暂停/RC6/worker。
## 5个提交路径
- src/backend/app/config_files.py：可选系统周期映射与health内部恢复比例类型；缺键保守返回gap；旧配置缺键时dump排除None，避免既有冻结配置形状/哈希漂移；禁止bool/字符串周期、缺/多周期及非1/5/20值。
- src/backend/app/feedback/{__init__,core}.py：纯冻结数据输入和确定性Decimal计算，无DB/网络/提醒/生命周期写入入口。
- src/backend/selfchecks/test_p2n08_core.py、fixtures/p2n08_operands.json：研究员golden仅测试oracle；DeepSeek仅24条纯合成delta/amount运算数。
## 核心规则
1. 模拟序列仅本人×版本，按建议/版本/跟踪期去重；同版本多实例按created_at/id先后取首个。周期读配置，先结论horizon、缺失再版本；未知跳过+gap。只complete且bool方向参与，false累计、true清零，其他状态跳过；exit_at/suggestion_id排序。可见时间/退出时间晚于as_of不参与；冲突来源不任意择一。
2. 成交按本人账户×证券的0→正→0段，含全部输入费用税；部分减仓不结束，平本跳过、正收益清零，缺开仓段跳过+gap。只输入active且PIT可见的成交；重复同id相同行幂等，冲突修订拒绝；真实冲正投影读取/事件持久化在后续切片。
3. 回撤仅接受调用方明确证明完整的本人NAV历史，(历史峰值-当前)/峰值×100，按原始Decimal比较阈值。缺NAV、零分母、未解析修订、跨用户/未来记录不假造0。
4. RC5聚合：disabled优先；任一已知触发为triggered；其余缺项/缺证为unknown，不凭一项正常宣称全部ok；不改动作或暂停实例。
5. 权重严格执行平滑胜率α10、β0.6、γ0.4、s5及Decimal tanh，clamp[0.3,1.2]；n<20权重1。关闭auto_downweight仅本人排序权重1，不改原始权重或健康值。
6. 仅计算published↔observing建议；低于0.8连续5日，恢复>=0.9联合10日；内部启用时恢复还须>=基线×配置比例，缺配置/基线/日值不冒充恢复。缺日清零；低于0.6/内部低于50%连续20日只返回review，永不自动retired、draft或simulating晋级。提供的交易日序列须来自项目日历，函数绝不自行推断周一至周五。
## 定向验证
42个唯一相关节点分批最终通过。对应golden084八场景、085二场景、087五场景、090四场景；086/088/089/091/092属于后续切片未验收。无golden标识/答案写入引擎。
命令（cwd=src/backend，PYTHONPATH=.）：`/tmp/rv7-backend-venv/bin/pytest -q selfchecks/test_p2n08_core.py`；仅本模块，未运行全量/coverage。初始36节点及新增5阈值、1类型缺证节点分别验证；修改只复跑受影响节点。
日志：/tmp/p2n08-slice1.log（36过）、p2n08-threshold.log（新增5+修改1过）、p2n08-types-config.log（1过）、p2n08-formula.log（手算锚点1过）、p2n08-dedup.log（2过）、p2n08-golden-final.log（受影响084/085十场景过）；重复节点不累计。
mypy --follow-imports=silent仅3源码通过；相关4路径ruff/diff通过；暂存5路径秘密扫描阻断0/警告0。
## 配置权限与后续TODO
现有config/risk_controls.yaml无sim_fail_horizon_by_horizon和health.internal_recover_ratio。未获配置写授权，未修改YAML、未把默认天数写进判断分支。需编排者授权配置负责人补系统映射intraday_t=1,short=5,swing=20,long=20及internal_recover_ratio=0.8（health实际文件落点若另有安排先确认）；当前缺映射会unknown，内部复验启用而缺比例不会恢复。测试在内存提供合同默认配置，并验证改配置后结果随之变化。
待续派：暂停边沿/期满恢复幂等、RC6五项as-of及冲正、健康与权重持久化/worker/HTTP接线、unavailable五交易日重算、evaluation.data_as_of最早时点。未声称只读HTTP/真实PG/生产资金NAV/分钟复权链验收；本切片纯计算，没有创建隔离服务或生产调度。
DeepSeek：reports/deepseek/P2N-08/，已授权渠道一次纯合成操作数草稿；草稿index-keyed对象本地归一化并逐条验证24条索引/范围，只作算术输入，规则/代码/预期/安全均本地，无私源/秘密/真实数据外发。
