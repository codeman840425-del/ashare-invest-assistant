# 评审 5c76866（worker 读写挂 imports 卷，加 CI 数据卷白名单）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 028c077-M2 的部署侧修复：worker 读写挂载与 api 同一个卷，IMPORT_STORAGE_PATH 一致；ingest、beat、signal-rt 不挂。
- CI 的 DATA_VOLUMES 只允许 api、worker、maint-cli 三个服务挂这个卷，三者都必须读写挂，挂载点必须等于各自的 IMPORT_STORAGE_PATH。
- 实测：check_secret_boundary 结果 OK；对应测试通过。
- B/M：无。
