# 宿主机配置（T-O08）

本目录的脚本都只新增独立文件，不改动系统已有的文件。每一项都有卸载脚本。

## dockerd 自启 + 免 sudo 使用 docker

本机 PID 1 是 tini 加 pod-daemon，没有 systemd，也没有 cron 或 rc.local，所以不存在可靠的开机钩子。
目前采用以下最小方案：

1. `deploy/scripts/start-dockerd.sh` 负责启动 dockerd。
   - 每次启动后，以及发现 dockerd 已在运行时，都会给 `/var/run/docker.sock` 设一条 ACL：`setfacl -m u:box:rw`。
   - ACL 生效的用户可用 `AIA_DOCKER_ACL_USERS` 配置。
   - 这样已经打开、但没拿到 docker 组的会话也能直接用 `docker`。
   - **不用 chmod 666**。
2. `deploy/host/dockerd-autostart/install.sh` 安装 `/etc/profile.d/zz-aia-dockerd.sh`。
   - 每次登录 shell 时调用 `deploy/scripts/ensure-dockerd.sh`。
   - dockerd 在运行、socket 可读写时，耗时约 0.02 s，直接返回。
   - 否则在后台、加锁调用 start-dockerd.sh。
3. `deploy/scripts/compose.sh` 和 `up.sh` 发现 docker 不可用时，会自己调用 start-dockerd.sh 自愈。

```bash
sudo deploy/host/dockerd-autostart/install.sh                # 安装（幂等）
sudo deploy/host/dockerd-autostart/uninstall.sh              # 回滚：删除 profile.d 钩子
sudo deploy/host/dockerd-autostart/uninstall.sh --remove-acl # 同时删除 socket ACL
sudo setfacl -x u:box /var/run/docker.sock                   # 仅删除 ACL；dockerd 重启后 socket 重建，ACL 也会消失
```

局限：非登录 shell 不会触发这个钩子。不过任何一次 compose.sh 或 up.sh 都会自愈。

## apt 代理修复

- 根因与修复写在 `apt/99aia-proxy` 里：关闭 apt 的 SRV 查询 `Acquire::EnableSrvRecords "false"`。
- 安装位置：`/etc/apt/apt.conf.d/99aia-proxy`。
- 不修改任何 sources。

```bash
deploy/host/apt/install.sh     # 安装（幂等）
deploy/host/apt/uninstall.sh   # 回滚
sudo apt-get update && sudo apt-get install --download-only -y hello   # 验证
```
