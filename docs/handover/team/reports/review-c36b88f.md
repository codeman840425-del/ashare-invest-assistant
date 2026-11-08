# 评审 c36b88f（契约 #41：/securities/* 统一 private, no-store；存储根目录不存在时 delete_raw 报错）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，干净导出或临时克隆 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 028c077-M2 已修：根目录不存在时抛 StorageRootMissingError，不再当作已删除，该行保留到下一轮重试。
- Dockerfile 不预建 imports 目录，所以 worker 没挂卷时会报错并保留行，不会出现假删除；挂卷由 5c76866 完成。
- 实测：c41 17/0 通过，其中 200、304、未捕获异常的 500 都带 private, no-store；tb46x 49/0 通过。
- 网关自产的 502/504 也要带这个头，由 f6c36ec 在 nginx 上补齐。
- B/M：无。
