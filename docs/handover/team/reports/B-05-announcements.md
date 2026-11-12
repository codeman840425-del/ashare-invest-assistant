# B-05 announcements｜2026-11-11 北京时间
- 恢复令后重新领取：20:16，时限2h；独立ds/B-05-announcements，基线origin/main=465e020，不叠加其他PR。
- 注册GET /api/v1/securities/{code}/announcements；真实AuthDep、错误信封、ETag/304、private,no-store。
- 默认公开身份源：stock/index空态no_source、ETF not_applicable；items/sources空、next_cursor/data_as_of=null，固定disclaimer逐字。
- from/to按北京时间日期闭区间，category多值且严格枚举；limit默认配置50/最大200，非法参数400。
- 复用既有HMAC签名游标，scope绑定本人/证券/规范化筛选/固定排序；伪造、过期、跨用户/证券/筛选/接口与非法键均INVALID_CURSOR。
- published_at/id倒序，排他keyset分页；同时间按id区分，无重复遗漏；源重复键拒绝。
- 输出前校验https与配置url_host_allowlist，非白名单链接null；保留原始主机，不输出正文/摘要/改写内容。
- fixture仅本地/测试显式安装，按本人隔离；复用B-03原字节announcements.json及形状校验器。
- 定点35 passed，含401/403/404、隔离/304、日期类别、分页同时间、签名游标负例、URL协议/主机白名单、生产拒装。
- Ruff六模块通过；定向mypy两生产模块通过；免责声明类型注解修正后另跑1项形状smoke通过。
- 证据F:/workspace/team/status/B-05-announcements-pytest.xml及B-05-announcements-disclaimer-smoke.xml。
- 命令：cwd=src/backend，PYTHONPATH=<本任务绝对路径>/src/backend，UV_PROJECT_ENVIRONMENT=F:/workspace/team/venvs/B-05；uv run --offline --no-sync pytest selfchecks/test_b05_announcements.py -k b05。
- 提交/推前files、staged、完整推出范围secret_scan+gitleaks均执行；结果见PR/issue，原始报告仓库外。
- 仅内存SQLite身份表、内存会话和合成数据；无生产库/外呼/采集/部署，r2/B-06未动；不宣称生产公告源已可用。
- DeepSeek：复用B-03已复核草稿夹具；权限、游标签名、链接安全与最终验收本地完成。
申请新任务：按T-A158接续已授权factors空态端点。
