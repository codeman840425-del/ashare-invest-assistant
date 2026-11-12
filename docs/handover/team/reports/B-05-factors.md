# B-05 factors｜2026-11-11 北京时间
- 重新领取20:28，时限2h；独立ds/B-05-factors，基线origin/main=465e020，不叠加其他实现PR。
- 依据T-A158=f048f4a（PR #60），注册GET /api/v1/securities/{code}/factors；AuthDep/错误信封/ETag/304/private,no-store沿用。
- 默认无源：未指定trade_date时null，合法请求日期原样返回；factor_set_version=null、counts全零、items/sources空、data_as_of=null。
- ETF gap=not_applicable，股票/指数无数据=no_source；未知/旧代码404含superseded_by，日期非法/重复400。
- FactorCategory保持空枚举，任何未注册category（含B-03合成标签）400，不在meta/enums暗加正式类别。
- 本单仅可信空态；真实批次未接。显式本地/测试fixture也先清除B-03合成行/日期/版本，不将其作为HTTP行情。
- HTTP额外拒绝非空行/版本、非零counts、无据日期/时点/来源等越界源输出，返回安全错误信封，不泄漏合成内容。
- B-03原字节factors.json及旧shape仅校验输入夹具；新HTTP空态按T-A158响应模型+独立字段/语义断言验收，不改共用旧shape。
- 定点含默认/显式fixture两条源的请求透传/null/ETF/指数、401/403/404、owner取认证、304、生产拒装和合成元数据泄漏负例。
- 命令：cwd=src/backend，PYTHONPATH=<本任务绝对路径>/src/backend，UV_PROJECT_ENVIRONMENT=F:/workspace/team/venvs/B-05；uv run --offline --no-sync pytest selfchecks/test_b05_factors.py -k b05。
- 定点31 passed，六模块完整Ruff、两个生产模块定向mypy通过；files/staged/完整推出范围双扫描见本PR交付记录；证据F:/workspace/team/status/B-05-factors-pytest.xml。
- 前端F-10另单交付，两字段可空；合入须配套T-A158契约PR #60、F-07 PR #54及F-10消费；前端mock全空data_as_of也须最终为null，不填非空值规避类型。
- 仅内存SQLite身份表、内存会话及合成源；无真实证书/数据/共享或生产库/外呼/调度/部署，r2/B-06未动。
- 与其他B-05实现PR共用三文件相同blob；合入时须保留全部独立路由注册增量。
- DeepSeek：复用B-03已复核草稿作为负例输入；契约/权限/安全边界与最终验收本地完成。
申请新任务：B-05四端点完成后由Chief安排评审及后续主线；B-06仍按原门槛等令。
