# S1-7：公开研究资产后继范围

2026-11-12 MST，按 Chief 11:50 裁定从 main `c18a74bc692bec7b9a253f4406527adb986fcca9` 新建；[逐件映射](asset-map.json)绑定原 PR/head/path/blob/SHA256 与新位置。
#28 的14件与#29的4件共18件，按原路径逐字节保留：8脚本、6公开来源manifest、4说明/报告；另加本说明与映射，数据本体不入库。
原 #28/#29 保持 open、原 head/base/分支；18件承接不代表下列7件已吸收，不代表原PR全部独有增量已替代，也不代表main已具备runner功能。
`python docs/strategies/T-R65/check_status_inputs.py ...` 与 `python docs/strategies/T-R65/check_sh_st_vs_eastmoney.py ...` 均在26行导入 `retest.t_r58.data`；两checker仅登记、不迁入，历史命令不能在本后继直接运行。
`runner_data.require_status_inputs`、`StockCache.prepare`、`judgement._delisting`及runner调用依赖原 `data.py`、`judgement.py`、`runner.py`、`runner_data.py` 四件改动和未合父链；本后继没有等价实现。
`pytest tests/backend/retest/test_status_inputs.py` 依赖原测试及上述父链；测试未迁入，原“17/42例通过”不作为本后继结果。
上述2 checker＋4 runner＋1 test均绑定#28@`b8f3037e2e1406bb6f00228f7619961d43c89cb8`原blob，登记“#81后继待明确吸收”；当前#81未因此获认吸收，本阶段不拆分或运行runner，不删import、不造空模块。
已保留8脚本自身不导入 `retest.t_r58`，构建仍需原参数所指公开输入；历史CSV/XLSX/HF/vipdoc路径仅描述原来源，不提供文件、不授权读取本机材料。
三个 `fetch_*.py` 与 `crosscheck_evidence_only.py` 完整CLI会联网；PDF交叉核需 `pypdf`、XLSX读取需 `openpyxl`。本轮不采集/安装/读原数据，不得用历史示例覆盖现有manifest或正式产物。
本说明限定原文当前解释：T-R65的302补齐、股票/区间数、校准over/under、快照、P9四分类及`state=pass`、17/42测试，均保留为原任务历史结论，本轮未重验。
T-R66b的“12/12正文明示、0矛盾、残余风险收口”仅保留原URL/摘要/作者结论；本轮未下载PDF、重核正文或升级`evidence_only`标签，不作交易/合规结论。
本轮仅核18来源/字节一致、7件原blob保全、Python/JSON静态及合成纯函数定点；不证明真实覆盖/runner集成/正式门禁，不运行策略/r2/holdout/采集/数据库；发布以实际head的GitHub CI为准。
