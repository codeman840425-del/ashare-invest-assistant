# 评审 94cddd8（T-O11 ⑴：aia_maint 补 3 项禁读验收，修正过时注释）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 按 T-O11-aia_deny-ruling.md 落实：verify-roles 补了 target_ciphertext、response_body、cooldowns.fingerprint 三条 expect_denied；grants.sql 注释改为两份清单分开写。
- 实测：在新库上 apply-roles 跑两次，verify-roles 71 OK、0 FAIL，3 条新断言都通过。
- m（运维）：如果 apply-roles 失败或角色不存在，verify-roles 会留下 t_o11_* 探针用户，因为清理连接失败。建议在入口先确认角色存在。
- B/M：无。
