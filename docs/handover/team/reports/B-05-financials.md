# B-05 financials｜2026-11-11 北京时间
- 独立分支 ds/B-05-financials，基线 origin/main=465e020；不叠加 #51/#56，不改 r2/B-06。
- 真注册 GET /api/v1/securities/{code}/financials；AuthDep、错误信封、ETag/304、private,no-store 沿用现有链。
- 默认源仅查公开身份：stock/index 无源空态，ETF not_applicable，data_as_of=null；未知/旧代码404含superseded_by。
- report_period 支持重复键/逗号多值；limit默认8/最大40；as_of仅接受ISO日期；非法/重复单值参数400。
- 本地/测试显式fixture源复用B-03原字节financials.json与b03_shapes；按本人隔离，staging/production拒装。
- fixture按available_from≤as_of过滤，未知available_from不出时点视图；金额字符串保持原样，无累计转单季。
- 自检：20 passed，含401/403/404、隔离/伪造owner、ETF/指数空态、304、日期边界与生产拒装。
- 命令：cwd=src/backend；PYTHONPATH=<本任务绝对路径>/src/backend；UV_PROJECT_ENVIRONMENT=F:/workspace/team/venvs/B-05；uv run --offline --no-sync pytest selfchecks/test_b05_financials.py -k b05。
- Ruff：6个受影响Python模块通过；定向mypy两生产模块通过；证据F:/workspace/team/status/B-05-financials-pytest.xml。
- 扫描：交付前files/staged与推出完整范围secret_scan+gitleaks均执行，结果随PR/issue记录；原始报告留仓库外。
- 仅内存SQLite公开身份两表、内存会话与合成fixture；无生产库/共享库/真实样本/外呼/采集/部署。
- 与其余B-05独立PR共享的subresource_read.py/b05_harness.py/b03_shapes.py保持相同blob；路由注册增量须保留全部端点。
- 限制：真实HTTP路径及fixture打样，不宣称生产财报已可用；无真实证书数据读取或回补。
- DeepSeek：复用B-03已复核草稿夹具（reports/deepseek/B-03/）；契约、权限、安全和最终验收本地完成。
申请新任务：按已授权B-05顺序继续fund-flows→factors→announcements。
