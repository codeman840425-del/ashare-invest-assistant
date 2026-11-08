# 评审 7f3f9ba（grants.sql、verify-roles.sh）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 与 plan 7.3 第 7、8 条一致：aia_maint 用 maint_deny 拒绝 §1 列出的列；worker 使用 aia_api，只有 DML 权限；aia_api 不能读 licence 密文。
- 实测：verify-roles 54 OK / 0 FAIL（11-01，库 m7f3f）。
- m（运维）：grants.sql:16 的注释“两处 aia_deny 保持一致”已经过时。verify-roles 缺 aia_maint 对 target_ciphertext、response_body、cooldowns.fingerprint 的行为断言。详见 T-O11-aia_deny-ruling.md。
- B/M：无。
