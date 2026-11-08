# 评审 0f8129b（T-B48：v0.2.9 同步，持仓 #1–#3、CandidateSignalEventCause、/meta/enums）

- **结论：有条件通过**。没有 B；**不能单独推送**：单独看这个提交，`check_contract --meta-json` 会报 `/meta/enums` 缺 `candidate_decision`、`research_candidate_origin`、`research_candidate_status`（这是本提交的缺陷，83a031c 补上了）。必须和 83a031c 一起推，或者在它之后推。

## 问题
- M1（原 M1 只修了一部分）：`portfolio.py` 按 v0.2.9 #1–#3 改了 `security_type`、可转债的 null 和 estimated，但 **R6③ 的可空性没改**（相关字段的 schema 仍不可空或不一致）——后端
- M2（原 M2 未修）：现价只取持仓快照的 `last_price_ref`，不读日线收盘价（`portfolio.py` 模块说明第 5 行）；契约要求用日线收盘或实时价，并标明 data_as_of——后端
- m1（原 m1 未修）：`exposure.sector` 永远是 `[]`，只出 gap（`portfolio.py:373,393`）；行业数据要等 T-B43（见 plan 4.2 新增段）。在此之前保留 gap 即可
- m2：枚举缺口（见上），83a031c 已修

## 测试
ruff、mypy、静态检查通过；只有 meta-json 枚举一项失败；fixtures 的问题是已有的。

## 谁做什么
后端修 M1、M2；行业数据就位后再修 m1。
