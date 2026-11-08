# 评审：d1a148f fix(deploy): T-O13 补——nginx 断开外部 DNS（dns: <host>）

评审人：项目架构师　时间：2026-11-01（America/Denver）　方式：只读，/tmp 干净导出，静态审查 + 运行 Python CI 测试；**未起容器**

## 结论：设计正确，可推送；CI 检查有 2 个 m 级漏洞待补；上线前须完成停机演练和 T-O13 报告（上线门槛，不阻塞本次推送）

## 改动
- `docker-compose.yml`：nginx 加 `dns: [<host>]`，附长注释。
- `check_gateway_limits.py` 规则 9：base 中 nginx 的 dns 必须等于 `[<host>]`（接受字符串写法）；dev 不许设 dns。
- `nginx_limits_smoke.sh`：容器加 `--dns <host>`；删掉上游后要求严格 502；在网关内 `nslookup aia-no-such-host-o13 <host>` 必须没有 Address。
- 测试：4 个反例（base 删掉、<host>、追加 <host>、dev 覆盖）和 1 个字符串写法正例。

## 验证（d1a148f 导出）
- `pytest scripts/ci/tests`：446 passed。
- `check_gateway_limits`：0 个问题（含“外部 DNS 已断开”）；`check_secret_boundary`：OK。

## 运维关注点逐条
### ① <host> 与 dns: <host> 的关系 —— 正确，没有超时挂起
- 容器 resolv.conf 仍写 `nameserver <host>`；`dns:` 只改变内嵌 DNS 的**外部上游**。服务名（api 等）由 <host> 直接回答，不受影响。
- 对照 moby 源码（`daemon/libnetwork/internal/resolvconf` 的 TransformForIntNS；旧版 sandbox_dns_unix.go 注释也是“--dns 127.0.0.x 指容器自身 namespace 的 loopback”）：用户给的 dns 标为 `HostLoopback=false`，内嵌 DNS 在**nginx 容器自己的 namespace** 访问 <host>:53。那里没有监听，UDP 立刻 ECONNREFUSED，内嵌 DNS 很快回 SERVFAIL，不会等到超时。另有 nginx `resolver_timeout 3s` 兜底。
- 设了 dns 后内嵌 DNS 也不会回落到默认公共 DNS（只在没有任何 nameserver 时才用默认值）。
- 运维在 aia-t01 实测（外部名解析失败、重建 api 约 2 s 502、nginx 不重启）与上述一致。
- 前提：目标宿主 Docker 版本的行为一致，需在演练里记版本号并实测（见 ④）。

### ② 上游名字与搜索域 —— 无外泄路径
- nginx.conf 只有一个上游：`map $host $aia_api_upstream { default "api:8000"; }`，是短名，没有固定后缀。5 处 proxy_pass 都经过该变量；`resolver <host> valid=10s ipv6=off`。
- nginx 自带 resolver 不使用 resolv.conf 的 search/ndots，内嵌 DNS 也不补全；短名不会被拼成宿主搜索域发出去。
- healthcheck 探的是 <host>（不需 DNS）；只监听 80，没有 ssl_stapling/OCSP 之类需要外部 DNS 的配置。
- compose 用默认网络，没有 network_mode。

### ③ CI 能否发现删除/覆盖 dns —— 主要写法都能拦，有漏洞
能拦：base 删掉 dns、改成其他地址、追加地址、dev 里设 dns（compose 合并时 dns 列表是追加，dev 写 <host> 会变成 [<host>, <host>]，已拦）。
实测漏掉（在导出副本里改文件后跑 check_gateway_limits）：
- **m1**：`resolver <host> <host> …` → 0 个问题、rc=0。nginx 会在多个 resolver 间轮询，直接从 nginx 查外部 DNS，完全绕过 `dns:`。规则应要求 resolver 行**只能**有 <host>。同理，map 只检查了 default，新增 `~xxx 主机：<host> 分支也应限制为内部短名。
- **m2**：dev 文件给 nginx 加 `network_mode: host` → 0 个问题、rc=0。host 网络不经过内嵌 DNS，会改用宿主的解析。规则应禁止 nginx 在任何 compose 文件设 network_mode（或 networks 以外的网络模式）。
- n：`dns: !reset []` / `!override` 会让 yaml.safe_load 抛异常，rc=1 能失败但报错不清楚；建议捕获后给出明确提示。
- n：只扫 base 和 dev 两个文件。`deploy/scripts/compose.sh` 显式传 -f，不会自动加载 `docker-compose.override.yml`；但有人直接在 deploy/compose 下跑 `docker compose` 时会加载。建议 CI 发现 deploy/compose 下多出任何 compose 文件就报错，或一并扫描。`extends` 同理。

### ④ 上线前必须完成（上线门槛）
1. **上游停机演练（T-O13）**，在目标宿主（生产 Docker 版本）执行并记录：
   - `docker version`；
   - 停/重建 api：网关返回 502 的时长、nginx 不重启、恢复时间 ≤ valid=10s；
   - 网关内解析一个不存在的名字：SERVFAIL/无地址，耗时 < 1 s（证明没有超时挂起）；
   - 停机期间 nginx 无对外连接（抓包或 conntrack 看 53 端口和外部地址）。
2. **T-O13 报告**写完并归档到 /workspace/team/reports，含以上数据。
3. `nginx_limits_smoke.sh` 在有 Docker 的 CI 或目标宿主上实跑通过一次（本次评审没有起容器，没跑）。
4. 建议上线前补上 m1、m2（改动小）；不补也要在 T-O13 报告里写为已知风险。

## ingest 是否受影响 —— 不受影响
- ingest 直接请求 `MAIRUI_BASE_URL`（<url> dns，用的是默认的内嵌 DNS 和宿主上游；不经过 nginx。后端也没有任何经 nginx 出站的路径。本提交只改 nginx 服务。

## 谁做什么
- 运维：④ 的 1–3（上线前必须）；补 CI 规则 m1、m2 和 n 项。
- 测试角色：给 m1、m2 各补一个反例测试。
- 架构师：T-O13 报告交来后复核。
