# S1-7：公开研究资产后继范围

2026-11-12 MST，按 Chief 11:50 裁定，从 main `c18a74bc692bec7b9a253f4406527adb986fcca9` 新建研究后继。这里的当前范围说明适用于随本后继保留的历史 README、报告和 manifest；原文中的“完成”“全绿”“收口”均须按其原任务、来源及时间理解。

[逐件映射](asset-map.json)列出 #28 的 14 件及 #29 的 4 件独立公开资产，每件绑定原 PR、完整 head、路径、Git blob、SHA256 与新位置。18 件按原路径逐字节保留，共 8 个脚本、6 个公开来源 manifest、4 个说明/历史报告；数据本体不随迁移提交。另有本说明与映射两份新增材料。

本后继承接公开资产的内容与来源，不承接尚未合入 main 的 runner 功能。原 #28、#29 保持 open、原 head/base/分支不变。18 件已经映射不表示其余 7 件已经吸收，也不表示原 PR 的全部独有增量已被本后继替代。

## 仍依赖未合父链的命令

以下文件只登记在映射的 `deferred_parent_assets`，本后继不提供实现；需由 Chief 指定的 #81 后继逐件承接并核实后才具备相应前提。

| 历史命令或调用 | 所需父链 | 当前状态 |
|---|---|---|
| `python docs/strategies/T-R65/check_status_inputs.py ...` | checker 在第 26 行导入 `retest.t_r58.data`；还需原公开输入及日历/覆盖清单 | checker 未迁入，不能在本后继按历史命令直接运行 |
| `python docs/strategies/T-R65/check_sh_st_vs_eastmoney.py ...` | checker 在第 26 行导入 `retest.t_r58.data`；还需原公开输入 | checker 未迁入，不能在本后继按历史命令直接运行 |
| `runner_data.require_status_inputs`、`StockCache.prepare`、`judgement._delisting` 及 runner 调用 | 原 `data.py`、`judgement.py`、`runner.py`、`runner_data.py` 改动和未合入的 runner 父链 | 四件改动未迁入；没有本后继内的等价实现 |
| `pytest tests/backend/retest/test_status_inputs.py` | 原测试及上述 runner 父链 | 测试未迁入；原“17/42 例通过”不能作为本后继结果 |

这 2 个 checker、4 个 runner 文件和 1 个测试，均绑定 #28 head `b8f3037e2e1406bb6f00228f7619961d43c89cb8` 的原 blob，状态为“#81 后继待明确吸收”。现有 #81 不因此被认定已经吸收；本阶段不拆分或运行 runner，不删 import、不造空模块。

## 已保留脚本的使用前提

七个 T-R65 构建/抓取脚本与 T-R66b 公告交叉核脚本自身不导入 `retest.t_r58`。构建脚本仍需要其原参数指定的公开来源输入文件；提到的 CSV/XLSX/HF/vipdoc 库存路径是历史来源描述，本后继不提供这些文件，也不据此授权读取本机材料。

`fetch_cninfo_st_events.py`、`fetch_cninfo_per_stock.py`、`fetch_eastmoney_cym.py` 和 `crosscheck_evidence_only.py` 的完整 CLI 会联网；公告交叉核还需 `pypdf`，XLSX 读取需 `openpyxl`。本轮没有执行抓取、安装这些可选依赖或读取历史数据；保留脚本不等于授权重新采集。不得直接用历史示例覆盖现有 manifest 或正式产物。

## 历史结论与本轮验证的边界

T-R65 的 302 号段补齐、股票/区间数、校准 over/under、快照核对、P9 四分类及 `state=pass`、17/42 项测试结果，均是原文绑定的历史记录。本轮不读取真实 bundle，不复算它们，不运行策略、r2、holdout、采集或数据库流程。

T-R66b 的“12/12 正文明示”“0 矛盾”“残余风险收口”仅保留原公告 URL、PDF 摘录和原作者结论。本轮没有下载 PDF、重新核公告正文或晋级标签；`evidence_only` 是否升级为 `body_evidence`/`by_rule` 仍须原裁定流程，不产生交易或合规结论。

本轮验证限于 18 件来源/字节一致、7 件依赖的原 blob 保全、Python/JSON 静态可读性及明确标作合成的纯函数定点。它们不证明历史结论、真实输入覆盖、runner 集成或正式门禁通过；最终发布状态以本候选实际 head 的 GitHub CI 为准。
