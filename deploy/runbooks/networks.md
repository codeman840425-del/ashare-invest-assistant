# 容器网络拆分（T-O68）

契约 §7.11.5 / plan R19 的网络层纵深：运行时只让 ingest 出公网。应用层 netguard 仍只装在 ingest 进程里；本文件只讲 compose 网络。

## 四张网

| 网络 | 属性 | 谁接入 |
|---|---|---|
| `default` | `internal: true` | 漏写 `networks` 的服务（fail-closed，出不了网） |
| `<前缀>_internal`（`aia_internal`） | `internal: true` | 全部服务 |
| `<前缀>_egress`（`aia_egress`） | 默认可出网 | **仅 ingest**（扩表白名单须经编排者裁定） |
| `<前缀>_edge`（`aia_edge`） | 非 internal，但 `enable_ip_masquerade=false` | nginx；dev 覆盖里发布端口的 postgres / redis |

`internal: true` 的网络通常无法把 `ports:` 发到宿主，所以 nginx（以及本地调试的 postgres/redis）另挂 `aia_edge`。关闭伪装是为了让这张网没有实用的公网 SNAT，不是防火墙域白名单。

CI：`scripts/ci/check_compose_networks.py`（`secret-boundary` job）。

## 收口部署时在用户电脑上验证

本仓库开发机没有默认 `bridge` 网，compose 网络无法在那台上完整实测。上线或收口时请在用户 Docker 环境执行（不要 `down -v`、不要删别人的容器/卷）：

1. `deploy/scripts/compose.sh config` 能通过，且输出里各服务的 `networks` 与上表一致，只有 ingest 出现在 `*_egress`。
2. 在已启动的栈上（或同等网络）：
   - 从 `api` / `worker` / `beat` / `signal-rt` / `nginx` 容器访问公网（例如 `https://example.com` 或 `1.1.1.1:443`）应失败。
   - 从 `ingest` 容器访问公网应成功（回放模式可改用对非麦蕊地址的探测；live 不要为测网去打麦蕊）。
   - 宿主 `curl -sS --noproxy '*' http://127.0.0.1:${NGINX_HTTP_PORT:-8080}/health/live`（或项目约定的健康路径）应可达。
   - dev 叠加时宿主应能连 `127.0.0.1:${POSTGRES_HOST_PORT:-55432}` 与 redis 调试端口。
3. 确认 `aia_edge` 的 `com.docker.network.bridge.enable_ip_masquerade=false` 在本机 Docker 版本上确实挡住出站；若无效，记为残余风险并考虑 iptables / 独立防火墙。
4. DNS：nginx 已设 `dns: 127.0.0.1`（T-O13）。ingest 走 egress，DNS 查询可能出网，网络层兜不住（见报告残余风险）。

不要把服务改成 `network_mode: host`，否则本拆分全部失效。
