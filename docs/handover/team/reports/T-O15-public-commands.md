# T-O15 父代理公开操作命令（本执行器未运行）
- cwd：/workspace/team/runtime/T-O15；22:55 MST guard PID89409已在运行，先确认仍存活；58001已确认空闲。
```bash
umask 077
cd /workspace/team/runtime/T-O15
nohup env -i HOME=/workspace/team/runtime/T-O15/tunnel-home PATH=/usr/bi<path> /workspace/team/runtime/T-O15/bin/cloudflared tunnel --config /workspace/team/runtime/T-O15/quick-tunnel.yml --no-autoupdate --url <url> --metrics <host>:58001 --management-diagnostics=false --loglevel info </dev/null >/workspace/team/runtime/T-O15/cloudflared.log 2>&1 & pid=$!; python3 /workspace/team/runtime/T-O15/record-tunnel.py "$pid"
```
- 必须确认record成功；失败则停止本任务nginx/api，不分发URL；命令参数/cwd不得变更，否则专用身份核验拒绝。
- 日志：/workspace/team/runtime/T-O15/cloudflared.log（600）；元数据：tunnel-metadata.json（PID/starttime_ticks/boot_id/argv/cwd/记录时间），另有tunnel.pid。
- 从该日志读取实际http<path><随机主机>.<url>.com，不含路径、端口或末尾斜杠，再执行：
```bash
python3 /workspace/team/runtime/T-O15/set-public-url.py '<url>'
```
- 更新器核验live专用PID身份、URL确在该日志、精确HTTPS主机；扫描通过才原子写runtime JSON，Secure=true，仅重建api并验本地ready200/imports401。
- 然后父代理另验真实外部HTTPS登录页200与未登录/imports401，成功再给用户URL；不创建/审批账号。
- 立即关闭：python3 /workspace/team/runtime/T-O15/stop-preview.py；22:55 MST自动调用同入口，校验PID/starttime/boot/UID/exe/cwd/argv后用pidfd TERM/KILL，随后停本地栈并删host配置。
