# T005 环境盘点报告

- 检查时间：2026-11-01 12:08–12:12（MDT，UTC-7）
- 主机：grok-bot-vm-513286157，用户 `box`（uid 1000，组 box、orbitd）
- 方式：只读检查 + 最小验证；未安装任何组件，未改 /etc、未改 docker 配置、未加用户组，未调用麦蕊任何接口。

## 1. 现状

| 项目 | 结果 |
|---|---|
| OS | Debian GNU/Linux 13 (trixie) |
| 内核 | Linux 6.12.94+ x86_64（PREEMPT_DYNAMIC） |
| CPU | 8 核，Intel(R) Xeon(R) Processor |
| 内存 | 共 15 GiB，已用 9.3 GiB，可用约 6.4 GiB；无 swap |
| 磁盘 / | /dev/vdb ext4 128G，已用 5.7G（5%），可用 122G |
| /workspace | 不是单独挂载点，位于根分区 /dev/vdb（可用 122G） |
| Docker 数据目录 | /var/lib/docker 不存在（未安装 Docker） |
| init | 非 systemd（PID 1 不是 systemd，没法用 systemctl） |
| Docker | **未安装**：没有 docker/dockerd 二进制，没有 /var/run/docker.sock，没有 docker/containerd/moby 的 dpkg 包，也没有 podman/nerdctl/containerd。注意：网卡里有 docker0 网桥（<host>/16，linkdown），是残留或镜像预置的，没有对应的 daemon |
| docker compose v2 / docker-compose | 都不可用 |
| sudo | `sudo -n true` 成功 → **sudo 免密可用** |
| Python | Python 3.13.5；pip 25.1.1（系统 /usr/lib/python3/dist-packages）；`python3 -m venv` 可用（已验证后删除） |
| Node | node v24.22.1；npm 11.21.1；pnpm 10.34.6；yarn 未安装（有 corepack：/usr/local/bin/corepack） |
| git | 2.47.3 |
| git 全局 user.name / user.email | **都未配置** |
| credential.helper | 未配置 |
| ~/.ssh | **目录不存在**（没有任何密钥） |
| gh CLI | gh 2.103.0（/usr/local/bin/gh）；`gh auth status`：没有登录任何 GitHub 主机 |
| `ssh -T <user>` | 失败：`Connection closed by <host> port 22`（exit 255）。github.com 解析到 <host>（透明代理/fake-ip），SSH 22 端口被代理关闭；本机也没有密钥 |
| 网络 | 本机只有 IPv4（<host>/24，网关 <host>），没有全局 IPv6 地址；DNS 把外部域名都解析到 <host>，出站流量经透明代理转发 |
| 公网出口 IPv4 | api.ipify.org 24 次采样都是 **<host>**（1 个 IP） |
| 公网出口 IPv6 | api64.ipify.org 24 次采样出现 **24 个不同的 IPv6**（2a09:bac1/bac5::/32 段）；ifconfig.me 24 次出现 22 个不同的 IPv6 |

## 2. 最小验证（Docker 容器）

- **没有执行**：Docker 未安装，按要求不安装，记为缺口。
- 因此 timescale/timescaledb:latest-pg16 和 redis:7-alpine 都没拉取，也没有拉取耗时数据；TimescaleDB extversion 和 Redis PING 都没验证。
- 没有创建任何容器或镜像，**不存在残留**。

## 3. 缺口

1. Docker Engine、docker compose v2 插件都没有 → 没法在本机跑 TimescaleDB/Redis 容器。
2. 非 systemd 环境：装了 Docker 也要手动启动 dockerd，或者用别的方式托管。
3. git 未配置 user.name/user.email，也没有 credential helper。
4. 没有 SSH 密钥；而且出站 SSH（github.com:22）会被代理断开，SSH 方式访问 GitHub 不通。
5. gh 未登录，目前没法通过 HTTPS + gh 访问私有仓库，也没法推送。
6. yarn 未安装（可以用 corepack 启用）。
7. 出口 IP 不稳定（详见第 5 节），是对接麦蕊的**阻断性风险**。

## 4. 建议安装/配置项（只是建议，未执行）

| 建议 | 原因 |
|---|---|
| 安装 Docker Engine + docker compose v2 插件（docker-ce 官方 apt 源或 Debian 的 docker.io + docker-compose 插件） | 跑 TimescaleDB/Redis 等依赖服务、复现测试环境。非 systemd 环境下要另外考虑 dockerd 怎么启动/守护。需要决定是给 box 加 docker 组，还是走 sudo（现在 sudo 免密） |
| 装好后重跑本报告第 2 节的验证 | 确认镜像能拉取（代理环境下 Docker Hub 访问情况未知）以及耗时 |
| 配置 git 全局 user.name/user.email | 提交需要 |
| `gh auth login`（HTTPS）+ `gh auth setup-git` 作为 credential helper | SSH 22 不通，建议走 HTTPS；如果一定要 SSH，可以试 `ssh.github.com:443`（未验证） |
| 视需要 `corepack enable` 启用 yarn | 项目用 yarn 时才需要 |
| 让网络/代理侧为麦蕊流量提供**固定的 IPv4 出口**（或关闭代理的 IPv6 出站） | 见第 5 节 |

## 5. 风险/遗留问题（重点：出口 IP）

**采样方法**：12:08:48–12:11:02（MDT），每约 5 秒采样一次，共两路并行，每路 24 次（约 2 分钟）：
- 路 A：api.ipify.org（只有 IPv4）+ ifconfig.me/ip（双栈）
- 路 B：api64.ipify.org（双栈）

**结果**：
- api.ipify.org：24/24 都是 <host>，IPv4 出口**稳定**（看起来像 Cloudflare <host>/16 段，WARP 类出口）。
- api64.ipify.org：24 次 24 个不同的 IPv6；ifconfig.me：24 次 22 个不同的 IPv6。几乎**每个请求换一个 IPv6 出口**（2a09:bac1::/32、2a09:bac5::/32，也是 Cloudflare WARP 段）。
- 本机没有 IPv6 地址，`curl -6` 失败；但是 `curl -4 <url>` 仍然返回 IPv6。说明是**透明代理（fake-ip <host>）在远端按目标域名的 AAAA 记录决定用 IPv6 出站**，客户端强制 -4 没用。

**结论**：
- 如果目标域名只有 IPv4（没有 AAAA）：观察到的窗口内出口只有 1 个 IP，满足“60 秒内 ≤2 个 IP”。
- 如果目标域名有 AAAA（双栈）：60 秒窗口（约 12 次请求）内会出现约 11–12 个不同的 IPv6 出口，**远远超过 2 个**，一定会违反麦蕊证书的限制。
- 麦蕊行情服务域名有没有 AAAA 记录**未核实**（按要求没调用麦蕊任何接口；也可以只查 DNS，不碰接口，但本机 DNS 被代理劫持成 <host>，在本机查不到真实记录，要在代理侧或外部确认）。
- 就算现在 IPv4 稳定，也只是 2 分钟观察，没法保证代理/WARP 的 IPv4 出口长期不变，也没法保证固定 IP 可以写进白名单。

**建议**：正式对接麦蕊之前，要在网络层确保麦蕊流量走固定的 IPv4 出口（专用静态出口/NAT 网关，或者在代理上把这个域名设成仅 IPv4 + 固定出口），然后对麦蕊域名做长时间（例如 ≥1 小时）的出口 IP 监测；在这之前不应在本机直接连麦蕊。

**其他遗留**：
- docker0 网桥残留，但没有 Docker：来源不明，装 Docker 时可能需要留意网段冲突（<host>/16）。
- 内存已用 9.3G/15G、无 swap：同时跑 TimescaleDB + Redis + 其他服务的时候要留意内存。
- 本机是多 agent 共享的机器，sudo 免密，权限较大，改系统配置要协调。

## 附录：出口 IP 原始采样

### 路 A（时间 / api.ipify.org / ifconfig.me）
```
12:08:48 <host> 2a09:bac5:636b:db9::15e:f1
12:08:53 <host> 2a09:bac1:76c0:3d0::50c:70
12:08:58 <host> 2a09:bac1:7680:3d0::10:50c
12:09:03 <host> 2a09:bac1:76a0:3d0::39d:48
12:09:08 <host> 2a09:bac5:636b:2828::400:34
12:09:14 <host> 2a09:bac5:6368:2828::400:59
12:09:19 <host> 2a09:bac5:636b:2832::401:22
12:09:24 <host> 2a09:bac5:636e:188c::272:13b
12:09:29 <host> 2a09:bac5:6368:3296::50a:1e
12:09:34 <host> 2a09:bac5:636f:3296::50a:39
12:09:39 <host> 2a09:bac1:76c0:3d0::50c:70
12:09:44 <host> 2a09:bac5:6368:166e::23c:19
12:09:49 <host> 2a09:bac5:636f:32aa::50c:18
12:09:55 <host> 2a09:bac1:76a0:3d0::259:d2
12:10:00 <host> 2a09:bac5:636b:2832::401:22
12:10:05 <host> 2a09:bac1:76a0:3d0::162:241
12:10:10 <host> 2a09:bac5:636e:32aa::50c:70
12:10:15 <host> 2a09:bac5:636a:283c::402:45
12:10:20 <host> 2a09:bac5:636c:dcd::160:125
12:10:25 <host> 2a09:bac5:636e:32b4::50d:17
12:10:30 <host> 2a09:bac1:76a0:3d0::50c:74
12:10:36 <host> 2a09:bac5:636f:1791::259:9c
12:10:41 <host> 2a09:bac5:636a:2446::39d:36
12:10:46 <host> 2a09:bac5:636b:de1::162:250
```

### 路 B（时间 / api64.ipify.org）
```
12:09:01 2a09:bac5:636e:188c::272:33
12:09:06 2a09:bac5:636f:2828::400:5d
12:09:11 2a09:bac5:6368:166e::23c:67
12:09:17 2a09:bac1:76e0:3d0::400:7
12:09:22 2a09:bac5:6368:2828::400:59
12:09:27 2a09:bac5:6369:32b4::50d:9f
12:09:33 2a09:bac1:76c0:3d0::39d:70
12:09:38 2a09:bac1:76a0:3d0::259:2f
12:09:43 2a09:bac5:6368:3296::50a:f
12:09:48 2a09:bac1:76a0:3d0::39d:1b
12:09:54 2a09:bac1:76e0:3d0::50c:18
12:09:59 2a09:bac5:636a:1032::19d:195
12:10:04 2a09:bac1:76e0:3d0::50a:39
12:10:10 2a09:bac5:636e:166e::23c:82
12:10:15 2a09:bac1:76a0:3d0::400:5d
12:10:20 2a09:bac5:636a:283c::402:45
12:10:25 2a09:bac5:636a:a0::10:480
12:10:31 2a09:bac5:636e:3296::50a:94
12:10:36 2a09:bac1:76a0:3d0::272:57
12:10:41 2a09:bac5:636e:188c::272:11c
12:10:47 2a09:bac1:7680:3d0::400:9
12:10:52 2a09:bac5:636f:2446::39d:1b
12:10:57 2a09:bac5:6368:2832::401:a
12:11:02 2a09:bac5:636a:2446::39d:2e
```
