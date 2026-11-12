# B-05 fund-flows｜2026-11-11 北京时间
- 独立ds/B-05-fund-flows，基线origin/main=465e020，不叠加#58/#56，不改r2/B-06。
- 注册GET /api/v1/securities/{code}/fund-flows；真实AuthDep/错误信封/ETag/304/private,no-store。
- 默认源仅读公开身份：stock/index=unavailable/no_source，ETF=not_applicable；空集data_as_of=null，未知/旧代码404含superseded_by。
- days默认60/最大250，与from/to互斥；from/to成对严格ISO日期且顺序正确；重复单值与越界参数400。
- 区间上限按market.trading_calendar实际is_open计数，逐个公历日期必须覆盖；>250开市日400，日历缺口503 CALENDAR_NOT_COVERED，不按星期推算。
- fixture复用B-03原字节fund-flows.json与校验器；显式本地/测试安装、本人隔离，staging/production拒装。
- fixture保持金额字符串、未知分档null及is_final原值，日期升序；支持days和闭区间窗口，空窗口时点null。
- 自检21 passed，含401/403/404、隔离/伪造owner、ETF/指数空态、304、250/251开市日与休市日/缺口负例。
- 命令：cwd=src/backend，PYTHONPATH=<本任务绝对路径>/src/backend，UV_PROJECT_ENVIRONMENT=F:/workspace/team/venvs/B-05；uv run --offline --no-sync pytest selfchecks/test_b05_fund_flows.py -k b05。
- 完整Ruff六模块通过，定向mypy两个生产模块通过；证据F:/workspace/team/status/B-05-fund-flows-pytest.xml。
- 交付门禁：8文件files/staged与推出完整范围secret_scan+gitleaks均执行，结果见PR/issue；原始报告留仓库外。
- 测试仅内存SQLite公开身份两表+显式合成日历、内存会话；无真实样本/共享或生产库/外呼/采集/部署。
- 与其余B-05 PR共用subresource_read.py/b05_harness.py/b03_shapes.py相同blob；各路由注册增量须保留。
- 限制：真HTTP路径+fixture打样，生产资金流源未接入；不宣称真实资金流可用，不造缺失字段。
- DeepSeek：复用B-03已复核夹具（reports/deepseek/B-03/）；权限、安全、日历边界与最终验收本地完成。
- RV-03 P2返修：503 details补date=请求区间第一个实际缺失日、coverage_start/end=日历全局真实边界；空日历边界null，不猜交易日。
- P2定点：原日历边界1项+新增6项（默认/fixture两源×头尾越界/空日历）7 passed，精确断言三字段；Ruff两模块/mypy本模块通过；证据F:/workspace/team/status/B-05-fund-flows-P2-pytest.xml。
申请新任务：请复核做#59 P2增量；其后继续已授权factors（T-A158已裁），announcements已交PR #63。
