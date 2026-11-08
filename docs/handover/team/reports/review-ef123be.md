# 评审 ef123be（T-B58：币种/单位必须有明确的元数据才确认；保留更正后的离线回放）：逻辑可推，CI 会红
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 只有精确的元数据字段并且取值明确，才确认币种/单位；不认识的取值不外推。原始取证文件不覆盖。
- 实测：tb58 54/0 通过。
- **B1（后端）**：selfchecks/tb58.py 有 12 个 ruff 错误，而且未按 ruff format 格式化，CI 的 backend ruff 会红。T-B58.md 只跑了 F/E9 规则子集。
- 要求：跑 ruff check . 和 ruff format --check . 并修到全绿。
