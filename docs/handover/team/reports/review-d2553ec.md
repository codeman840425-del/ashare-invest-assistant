# 评审 d2553ec（p13 T-R12e+f：V5i v5i_backfill 等）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在干净导出或临时克隆 /tmp/rv3 里跑，只读，没有推送，没有调用麦蕊。
- review-af589c0 的 M2 已落实：分析输出 v5i_backfill，包括 plrq 落在季末的占比，以及季末行与同期报告最早 plrq 的差值天数分布。
- 实测（在 076ad51 上，env -u MAIRUI_LICENCE，本地伪造服务端）：dry-run 158 PASS，客户端 28 次等于服务端增量；tr12_fin 52/0 通过；输出不含证书。
- m（后端）：selfchecks/tr12_fin.py:162 未按 ruff format 格式化。CI 只跑 ruff check，不检查格式，所以不会变红。
- B/M：无。
