# 评审 20fe5d3（T-B59：逐证券 CDR 签核、显式交易日历、带版本的股本类别名单草稿）：逻辑可推，CI 会红
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 实测：tb59 59/0 通过；secret_scan range b91d03a..7c0548a 阻断 0。
- **B4（后端）**：selfchecks/tb59.py 新增 30 个 ruff 错误，并且未按 ruff format 格式化。mypy 没有新增错误，现有 5 个都来自 1af8543。
- share_class_list.yaml 注明了来源、日期和数量限制（211 家与 209 家的差异尚未解决），符合 V5g“名单必须注明来源和日期”的要求。
