# T-R66b｜12 只 evidence_only 退市股公告正文交叉核（2026-11-11 北京时间，完成）
- 分支 `ds/T-R66b`（基于 `ds/T-R65@a782a1e`）；上游 T-A155 裁定 ③。
- 目标：`termination_list.csv` 窗口内 `no_period_evidence=no_title_evidence` 的 12 只（600260/600290/600297/000023/000616/000836/000861/002325/002503/002505/002619/300495）。
- 方法：逐股取巨潮「终止上市暨摘牌」公告 PDF（1.0s 间隔），pypdf 抽正文，匹配「不进入/不进行/不设退市整理期」、交易类强制退市、面值/市值/成交量/股东人数、主动退市/吸收合并，以及矛盾项「进入退市整理期」；保留 URL + PDF sha256 + 命中片段。
- 结果：**12/12 正文明示不进入/不设退市整理期且均为交易类强制退市**，0 矛盾 → evidence_only 残余风险逐股收口。002619 用「不设退市整理期」（其余 11 只为「不进入」）。
- 产物：`docs/strategies/T-R66b/README.md`、`manifests/evidence_only_crosscheck.json`、`crosscheck_evidence_only.py`；PDF 本体在仓库外 `F:/t-r66b-data/pdfs/`（不入库）。
- 本轮不改 `termination_list.csv`（重跑在跑，改 sha 会作废）；是否把这 12 只升级为 `body_evidence`/`by_rule` 待重跑判读时与架构师确认。
- 检查：secret_scan 待提交前跑；未调麦蕊、未写库、未碰他人 WIP。
- 申请新任务：T-R66 判读等重跑结果；如需可先把 12 只正文证据并入下一版标签。
