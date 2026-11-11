# T-R66b：12 只「无整理期标题证据」退市股的公告正文交叉核

> 任务：T-R66b｜2026-11-11 北京时间｜分支 `ds/T-R66b`（基于 `ds/T-R65@a782a1e`）
> 上游：T-A155 裁定 ③「12 只 evidence_only 逐股公告正文交叉核收口」

## 结论

- **12/12 正文明示「不进入/不设退市整理期」**，且均写明交易类强制退市；0 只与 `termination_list.csv` 的 `no_period_evidence=no_title_evidence` 标注矛盾 → T-A155 ④ 的残余风险已逐股收口。
- 本轮**不改** `termination_list.csv`（重跑正在使用该 sha，改了会作废）。建议重跑判读时与架构师确认：下一版是否把这 12 只从 `evidence_only` 升级为 `body_evidence`（正文证据）并入 `by_rule`。

## 方法

- 取 `termination_list.csv` 中窗口内（2022-01-04~2026-08-06）`no_period_evidence=no_title_evidence` 的 12 只。
- 逐股取巨潮「终止上市暨摘牌」公告 PDF（`static.cninfo.com.cn`，单线程 1.0s 间隔），`pypdf` 抽正文，模式匹配：`不进入/不进行/不设退市整理期`、`交易类强制退市`、`面值/市值/成交量/股东人数`、`主动终止上市/吸收合并`、以及矛盾项 `进入退市整理期`。
- 产物：`manifests/evidence_only_crosscheck.json`（逐股 URL、PDF sha256、页数、命中片段、裁决）；PDF 本体在仓库外 `F:/t-r66b-data/pdfs/`（不入库）。
- 复现：`uv run --no-project --with pypdf python docs/strategies/T-R66b/crosscheck_evidence_only.py --termination data/retest-inputs/termination_list.csv --per-stock-jsonl <per_stock.jsonl> --out <dir> --manifest docs/strategies/T-R66b/manifests/evidence_only_crosscheck.json`

## 逐股结果

| 代码 | 简称 | 终止日 | 正文关键句（节选） | 裁决 |
|---|---|---|---|---|
| SH:600260 | *ST凯乐 | 2023-02-15 | 者重大遗漏，并对其内容的真实性、准确性和完整性承担个别及连带责任。重要内容提示：●公司股票不进入退市整理期交易。●公司股票将于2023年2月 | no_delisting_period_confirmed |
| SH:600290 | *ST华仪 | 2024-01-16 | 者重大遗漏，并对其内容的真实性、准确性和完整性承担个别及连带责任。重要内容提示：公司股票不进入退市整理期交易；公司股票将于2024年1月 | no_delisting_period_confirmed |
| SH:600297 | 广汇汽车 | 2024-08-28 | 14条、第9.1.17条、第9.2.9条和第9.6.1条的规定，你公司股票及可转换公司债券不进入退市整理期交易，本所在公告本决定之日后的5个 | no_delisting_period_confirmed |
| SZ:000023 | *ST深天 | 2024-09-02 | 、第9.6.10条第二款的规定，你公司股票因触及交易类强制退市情形被本所作出终止上市决定，不进入退市整理期，你公司股票将于本所作出终止上市决 | no_delisting_period_confirmed |
| SZ:000616 | *ST海投 | 2023-08-23 | 、第9.6.10条第二款的规定，你公司股票因触及交易类强制退市情形被本所作出终止上市决定，不进入退市整理期，你公司股票将于本所作出终止上市决 | no_delisting_period_confirmed |
| SZ:000836 | ST富通 | 2024-08-12 | 1、深圳证券交易所已决定终止公司股票上市，2024年8月12日公司股票将摘牌。2、公司股票不进入退市整理期交易。3、公司股票终止上市后，将转 | no_delisting_period_confirmed |
| SZ:000861 | 海印股份 | 2024-09-18 | 、第9.6.10条第二款的规定，公司股票因触及交易类强制退市情形被深交所作出终止上市决定，不进入退市整理期，公司股票将于深交所作出终止上市决 | no_delisting_period_confirmed |
| SZ:002325 | *ST洪涛 | 2024-08-15 | 、第9.6.10条第二款的规定，你公司股票因触及交易类强制退市情形被本所作出终止上市决定，不进入退市整理期，你公司股票将于本所作出终止上市决 | no_delisting_period_confirmed |
| SZ:002503 | *ST搜特 | 2023-08-11 | 二款的规定，你公司股票因触及交易类强制退市情形被本所作出终止上市决定，股票及可转换公司债券不进入退市整理期，你公司股票及可转换公司债券将于本 | no_delisting_period_confirmed |
| SZ:002505 | 鹏都农牧 | 2024-08-30 | 6.10条第二款的规定，公司股票因触及交易类强制退市情形被深圳证券交易所作出终止上市决定，不进入退市整理期，公司股票将于深圳证券交易所作出终 | no_delisting_period_confirmed |
| SZ:002619 | *ST艾格 | 2022-04-28 | 核意见，本所决定你公司股票终止上市。你公司股票因触及交易类强制退市指标被本所终止上市决定，不设退市整理期，公司股票将于本所作出终止上市决定后 | no_delisting_period_confirmed |
| SZ:300495 | *ST美尚 | 2024-09-20 | 7.9条第二款的规定，你公司股票因触及交易类强制退市情形被深圳证券交易所作出终止上市决定，不进入退市整理期，你公司股票将于深圳证券交易所作出 | no_delisting_period_confirmed |

## 残余说明

- 002619 *ST艾格正文用「不设退市整理期」，已加入判据（其余 11 只为「不进入退市整理期」）。
- 裁决只依据公告正文与既有元数据（`expected_end_date`），不生成交易/合规结论；标注升级需裁定。
