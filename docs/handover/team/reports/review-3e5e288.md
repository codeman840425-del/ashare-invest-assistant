# 评审 3e5e288（T-B46-x/#35/T-B56 部分）：可推，但必须和 b3aab3c 同批推送
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 9e693b2-M1 已修：discard_import 不再删除原始文件；purge_expired_raw_files 每批 500 行，使用 skip_locked，失败时保留该行，日志只记异常类型。
- 旧 m2 已修：任务改名为 imports.purge_preview_rows。旧 m1 仍未修：purge_uncommitted_import_rows 没有分批（后续 3820276 会做分块清理）。
- 实测：selfchecks/tb46x 48/0 通过（PG16+timescale，alembic head）。
- 实测：2954b6c 加上 test/T-T01 的测试做全量 pytest，0 失败；总覆盖率 80.62%。
- 本提交的树含 S5 虚构<account-field>，单独推送时 secret-scan 会红。b3aab3c 已修；secret_scan range d5dd1f8..2954b6c 阻断 0。
- B/M：无。
