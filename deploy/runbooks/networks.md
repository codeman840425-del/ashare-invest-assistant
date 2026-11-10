# 容器网络拆分（T-O68）

契约 §7.11.5 / plan R19 的网络层纵深：运行时只让 ingest 出公网。应用层 netguard 仍只装在 ingest 进程里；本文件只讲 compose 网络。

## 四张网

| 网络 | 属性 | 谁接入 |
|---|---|---|
| `default` | `internal: true` | 漏写 `networks` 的服务（fail-closed，出不了网） |
| `<前缀>_internal`（`aia_internal`） | `internal: true` | 全部服务 |
| `<前缀>_egress`（`aia_egress`） | 默认可出网 | **ingest**；以及 opt-in profile `master-bootstrap`（主数据首导，默认不启动） |
| `<前缀>_edge`（`aia_edge`） | 非 internal，但 `enable_ip_masquerade=false` | nginx；dev 覆盖里发布端口的 postgres / redis |

`internal: true` 的网络通常无法把 `ports:` 发到宿主，所以 nginx（以及本地调试的 postgres/redis）另挂 `aia_edge`。关闭伪装是为了让这张网没有实用的公网 SNAT，不是防火墙域白名单。

CI：`scripts/ci/check_compose_networks.py`（`secret-boundary` job）。

## 收口部署时在用户电脑上验证

本仓库开发机没有默认 `bridge` 网，compose 网络无法在那台上完整实测。上线或收口时请在**用户 Docker 环境**、**已启动的栈**上执行（不要 `down -v`、不要删别人的容器/卷）。一律用 `deploy/scripts/compose.sh`，不要手写项目名。

**Windows：下列命令要在 WSL 或 Git Bash 里执行。** `${NGINX_HTTP_PORT:-8080}` 这类是 bash 写法，cmd.exe 不能直接跑。宿主上的 `curl` 也可以改用 PowerShell 的 `curl.exe`（见第 5 步），但容器内探测仍须走 WSL / Git Bash 里的 `compose.sh`。

探测只许用普通公网地址 `http://1.1.1.1` 或 `https://example.com`。**绝不调麦蕊，也不要打任何已授权上游。** 测完把命令输出记入收口记录。

### 探测命令（容器内没有 wget 时的替代）

`nginx` 镜像健康检查已用 `wget`；`api` / `worker` / `ingest` 等后端镜像有 `python`。下面函数按 wget → curl → python3 → python 依次尝试，5 秒超时。退出码 0 算出网成功（拿到了任意 HTTP 响应，含非 200）；非 0 通常算失败/超时。容器里没有客户端时函数会打印 `NO_HTTP_CLIENT` 再退出；**不要只看 rc=2**（wget/curl 自身也可能返回 2），看到该文本再改用 sidecar。

```bash
probe_egress() {
  local svc="$1" url="${2:-http://1.1.1.1}"
  deploy/scripts/compose.sh exec -T "$svc" sh -c '
    url="$1"
    if command -v wget >/dev/null 2>&1; then
      wget -T 5 -q -O - "$url"
    elif command -v curl >/dev/null 2>&1; then
      curl -sS -m 5 --noproxy "*" -o - "$url"
    elif command -v python3 >/dev/null 2>&1; then
      python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=5).read()" "$url"
    elif command -v python >/dev/null 2>&1; then
      python -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=5).read()" "$url"
    else
      echo NO_HTTP_CLIENT
      exit 2
    fi
  ' sh "$url"
}

# 容器内无 wget/curl/python 时（例如 dev 的 postgres/redis）：不改服务镜像，共用其网络命名空间。
# 镜像与 database.md 相同，用 alpine:3.21（含 wget）。若本机没有该标签，先在有出网的环境下
# docker pull alpine:3.21，不要对业务镜像 --pull always。
probe_egress_sidecar() {
  local svc="$1" url="${2:-http://1.1.1.1}" cid
  cid="$(deploy/scripts/compose.sh ps -q "$svc")"
  docker run --rm --network "container:${cid}" alpine:3.21 wget -T 5 -q -O - "$url"
}
```

判定（后文「通过 / 不通过」都按此）：

- **期望失败的出网**（非 ingest、以及检验 masquerade 的 edge 服务）：5 秒内超时、不可达、`Network is unreachable`、`No route to host`、`Connection timed out`、`Operation not permitted` → **通过**。若拿到了 HTTP 正文，或 TCP 已接通 → **不通过**，记残余风险，改用宿主防火墙。
- **期望成功的出网**（仅 ingest）：5 秒内拿到任意 HTTP 响应 → **通过**。超时或不可达 → **不通过**。

### 1. compose config

```bash
AIA_PROFILE=dev  deploy/scripts/compose.sh config >/dev/null; echo dev:$?
AIA_PROFILE=live deploy/scripts/compose.sh config >/dev/null; echo live:$?
deploy/scripts/compose.sh --profile master-bootstrap config >/dev/null; echo profile:$?
```

判定：三个退出码都是 0。需要核对 networks / ports 时再去掉 `/dev/null`，只看这两段，**不要把整份含插值的 config 存进工单**。默认 dev/live **只有 ingest** 出现在 `*_egress`；加上 `--profile master-bootstrap` 时该一次性服务也会出现在 egress，仍不得有 worker。所有 `ports` 的宿主地址必须是 `127.0.0.1`。核对完删除 `deploy/env/.env`（若这次才从 example 生成、且仓库不跟踪它）。

### 2. 非 ingest 服务出网应失败

```bash
for svc in api worker beat signal-rt nginx; do
  echo "=== $svc ==="
  probe_egress "$svc" http://1.1.1.1
  echo "rc=$?"
done
# dev 叠加里 postgres / redis 也挂 aia_edge，同样应失败：
# probe_egress_sidecar postgres http://1.1.1.1; echo rc=$?
# probe_egress_sidecar redis http://1.1.1.1; echo rc=$?
```

判定：列出的服务（以及 dev 的 postgres/redis）均按「期望失败的出网」通过。`nginx` 在 `aia_edge` 上，本项也是第 6 步伪装开关的交叉证据。

### 3. ingest 出网应成功（只打普通公网，绝不调麦蕊）

```bash
probe_egress ingest http://1.1.1.1
echo rc=$?
# 若 1.1.1.1 被本机策略拦截，可改用 https://example.com，仍然禁止麦蕊或任何已授权上游。
```

判定：按「期望成功的出网」通过。失败则检查 ingest 是否误挂成只走 internal。回放模式也用普通公网地址，不要为测网去打麦蕊。

### 4. 服务名 DNS

在 `api`（有 Python）上解析同栈服务名。不要用 `nginx` 容器的 `wget`/`getent` 测 Docker 服务名：它的 `/etc/resolv.conf` 上游是 `127.0.0.1`（T-O13，切断外部劫持），libc 查名字会 SERVFAIL；nginx 自己靠配置里的 `resolver 127.0.0.11` 解析 `api`，与本项不是同一条路径。

```bash
deploy/scripts/compose.sh exec -T api python -c "
import socket, ipaddress
for n in ('api', 'worker', 'ingest', 'nginx', 'postgres', 'redis'):
    ip = socket.getaddrinfo(n, None)[0][4][0]
    a = ipaddress.ip_address(ip)
    ok = a.is_private or a.is_link_local or a.is_loopback or (a.version == 6 and a.is_site_local)
    print(n, ip, 'OK' if ok else 'NOT-PRIVATE')
"
```

判定：每个名字都能解析，且地址是私有 / 链路本地 / 回环（IPv6 再加 site-local），**不是公网地址**。任一名字失败或落到公网 → 不通过。

ingest 走 egress，它的外部 DNS 查询可能出网，网络层兜不住。

### 5. 端口只在 127.0.0.1

bash / Git Bash / WSL（端口若在 `.env` 改过，替换默认值）：

```bash
curl -sS -m 5 --noproxy '*' -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:${NGINX_HTTP_PORT:-8080}/health/live
# 判定：2xx，或至少 TCP+HTTP 可达。连不上 → 不通过。

# 把 <lan-ip> 换成一块真实网卡地址（不要用 127.0.0.1）：
curl -sS -m 5 --noproxy '*' --connect-timeout 5 \
  http://<lan-ip>:${NGINX_HTTP_PORT:-8080}/health/live
# 判定：连接失败或超时 → 通过。若成功，端口暴露到局域网 → 不通过。

# Linux / WSL 核对监听地址（dev 再看 55432 / 56379，按 .env 调整）。
# Docker Desktop 下，WSL 里的 ss/netstat 常常看不到 Windows 宿主的监听；
# 这种情况以 PowerShell 的 Get-NetTCPConnection 为准，不要只看 ss 为空就判失败。
ss -ltn | grep -E ":${NGINX_HTTP_PORT:-8080}\b|:5432\b|:6379\b|:55432\b|:56379\b" || true
# 若 ss 有输出：应看到 127.0.0.1:端口，不应出现 0.0.0.0: 或 *:端口。
```

探测 TCP 是否在 127.0.0.1 上打开（不要用 `curl telnet://` 配 `-m`：超时退出码 28，容易误判）。
Git Bash 通常没有 `nc`，按下面顺序使用找得到的工具：

```bash
probe_tcp() {  # probe_tcp 127.0.0.1 55432
  local host="$1" port="$2"
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 5 "$host" "$port"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import socket,sys; s=socket.create_connection((sys.argv[1], int(sys.argv[2])), 5); s.close()" "$host" "$port"
  elif command -v python >/dev/null 2>&1; then
    python -c "import socket,sys; s=socket.create_connection((sys.argv[1], int(sys.argv[2])), 5); s.close()" "$host" "$port"
  elif [ -n "${BASH_VERSION:-}" ]; then
    timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null
  else
    echo "NO_TCP_CLIENT"; return 2
  fi
}
# dev 叠加时宿主还应能连调试口（不必登录）：
probe_tcp 127.0.0.1 "${POSTGRES_HOST_PORT:-55432}"; echo pg_rc=$?
probe_tcp 127.0.0.1 "${REDIS_HOST_PORT:-56379}"; echo redis_rc=$?
# 判定：127.0.0.1 上 TCP 接通 → 通过；对 <lan-ip> 同样端口应失败。
# 输出含 NO_TCP_CLIENT 时换工具，不要当成端口失败。
```

PowerShell（仅宿主编译与监听核对；容器内探测仍走 WSL / Git Bash）：

```powershell
curl.exe -sS -m 5 --noproxy * -o NUL -w "%{http_code}`n" http://127.0.0.1:8080/health/live
# 再用本机局域网 IP 替换 127.0.0.1，应连接失败。
# Docker Desktop：在 Windows 侧看监听（不要只依赖 WSL 里的 ss）：
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8080,55432,56379 } |
  Select-Object LocalAddress, LocalPort
# 判定：LocalAddress 应为 127.0.0.1，不应为 0.0.0.0 或 ::。
```

### 6. Docker Desktop 对 `enable_ip_masquerade=false` 的实际效果

`aia_edge` 关闭了 `com.docker.network.bridge.enable_ip_masquerade`。在已启动的栈上对 **nginx**（以及 dev 的 postgres/redis）再跑第 2 步同一条探测：

```bash
probe_egress nginx http://1.1.1.1; echo rc=$?
# dev：probe_egress_sidecar postgres http://1.1.1.1; probe_egress_sidecar redis http://1.1.1.1
```

判定：

- 按「期望失败的出网」通过 → 本机尊重该开关，本项通过。
- 若 nginx（或 dev 的 postgres/redis）**能**访问 `http://1.1.1.1` → 本机 Docker Desktop / vpnkit 可能无视该选项（有第三方报告称 vpnkit 仍做 NAT），`aia_edge` 上的服务仍可能出网。记为残余风险，改用宿主防火墙，本项不通过。

### 7. WSL mirrored 模式

若用户电脑启用了 WSL mirrored（`.wslconfig` 里 `networkingMode=mirrored`），在 **WSL 发行版内**与 **Windows 侧**各做一遍第 2、3、5、6 步。Windows 侧只测宿主端口（第 5 步的 `curl.exe`）；容器内出网探测仍在 WSL 里跑。

判定：两侧都满足「非 ingest 出网失败、ingest 出网成功、端口只在 127.0.0.1、edge 不出网」。任一侧 `127.0.0.1` 不可达，或局域网 IP 能连上发布端口，或出站隔离失效 → 不通过，记入收口记录并排查。非 mirrored 的 WSL 也建议从 Windows 侧抽查：`127.0.0.1` 可达、局域网 IP 不可达。

### 8. 不要改成 host 网络；ingest 仍是全网出口

不要把服务改成 `network_mode: host`，否则本拆分全部失效。

**ingest 自身仍是全网出口**：网络层只限制「哪只容器能出网」，不限制 ingest 出到哪些地址。ingest 被利用后仍可任意外发，靠应用层 netguard（契约 §7.11.5），网络层兜不住。

## 主数据首导的一次性出网（编排者裁定 ④，2026-11-09）

默认栈与 `maint-cli` 不出网。需要联网从三所官网拉公开 HTTPS 主数据时，只通过 `deploy/scripts/master-bootstrap.sh` 启动 opt-in 服务（加入 `aia_egress`），以保留 `--check`、flock、`--confirm-network-fetch` 和 CI 拒绝。不要直接 `compose.sh run`。

```bash
deploy/scripts/master-bootstrap.sh --check; echo "rc=$?"
# rc=10 且确认本机可访问交易所网站后：
deploy/scripts/master-bootstrap.sh --run --confirm-network-fetch
```

跑完容器即删（`--rm`），不要常驻，不要把该 profile 加进默认 `up.sh`，**不要调麦蕊**。CI 出网白名单只登记 `ingest` 与这个一次性服务。
