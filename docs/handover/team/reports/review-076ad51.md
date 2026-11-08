# 评审 076ad51（p13 T-R12g：V5i 截止日规则只用于首次回填的季末行，增量行取 first_seen_at）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在干净导出或临时克隆 /tmp/rv3 里跑，只读，没有推送，没有调用麦蕊。
- 与 9ad51b8 的 T-R12g 确认一致。capital_deadline 已实现，af589c0 的 M3 关闭；select 改为精确匹配，m1 也关闭。
- 实测：同 d2553ec，dry-run 158 PASS，tr12_fin 52/0 通过。
- B/M：无。
