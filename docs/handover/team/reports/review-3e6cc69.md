# 评审 3e6cc69（主密钥备份 T-A04 ⑧：b195ca6 的评审项 M1、m1、m2）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在干净导出或临时克隆 /tmp/rv3 里跑，只读，没有推送，没有调用麦蕊。
- 路径一律用 realpath 规范化后再判断“在仓库内”或“在密钥目录下”。*.dump 检查扩展到子目录和各级上级目录。restore 时没有 .sha256 就必须带 --expect-sha256，否则不恢复。umask 077，目录权限 700。
- 日志只打印 sha256 的前 16 位，不打印密钥。
- 实测：test_app_master_key_backup 包含在 scripts/ci/tests 648 个通过的用例里。
- B/M：无。
