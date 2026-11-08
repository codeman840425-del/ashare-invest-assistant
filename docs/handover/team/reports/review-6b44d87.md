# 评审 6b44d87（CI 规则 7：按服务的 secret 白名单 SERVICE_SECRETS）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 每个服务的白名单与 plan e56462c 的按服务分配主密钥一致：api 挂公钥和主密钥，worker 只挂主密钥，ingest 挂私钥和公钥，db-roles 挂 3 个口令，maint-cli 挂 maint 口令，其余服务不挂。
- 三类情况都会拒绝：表外服务、服务挂了表外 secret、顶层定义了未登记的 secret。MASTER_KEY_ALLOC 由白名单派生，不再单独维护。
- 实测（临时克隆，HEAD=f6c36ec）：scripts/ci/tests 605 通过，55 跳过；check_secret_boundary 结果 OK。
- 注：在 git archive 导出里跑会有 26 个 gitignore 用例失败。原因是导出不是 git 仓库，check-ignore 用不了，不是缺陷。
- B/M：无。
