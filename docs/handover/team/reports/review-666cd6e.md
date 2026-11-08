# 评审 666cd6e（T-O13 CI 补充，跟进 review-d1a148f）+ T-O13 演练报告结论

- 评审人：架构师；日期：2026-11-01（America/Denver）
- 方法：干净导出到 /tmp/rv/666cd6e；`check_gateway_limits.py` 真实仓库 rc=0；`scripts/ci/tests/test_gateway_limits.py` **82 passed**（与 T-O13.md §5 一致）；全量 556 passed / 5 failed（test_secret_scan 导出环境问题，父提交同样失败）。在导出副本的拷贝上做绕过实验（工具 /tmp/rv/tools/exp.py + gw_cases.py），未修改仓库。

## 结论：**可以推送**（无 B / M）

## 1. 五项要求逐项实验

| 要求 | 实验 | 结果 |
|---|---|---|
| resolver 只允许 <host> | `resolver <host> <host>` | 拦下 ✅（`<host>:53` 也会被拦，属从严误杀，可接受） |
| map 分支只限内部短名 | 加 `"evil.example.com:443"` 分支；加 `<host>:53` 分支 | 都拦下 ✅ |
| nginx 禁 network_mode / extends | dev 文件 `network_mode: host`；base `network_mode: service:api`；dev `extends` | 都拦下 ✅ |
| !reset 报错 | dev 文件 `dns: !reset []` | 明确报错并给行号 ✅ |
| override 文件纳入检查 | 新增 `deploy/compose/docker-compose.override.yml`（改 dns）；新增 `compose.yaml` | 都拦下 ✅ |

补充实验：dev 文件让 nginx 通过 `networks:` 加入 `external: true, name: host` 的网络——检查器放行，但 Docker Compose v5 实际 `up` 报错（host 网络不支持网络别名），不构成可用绕过，记 n。

## 2. 问题

- **m1** `scripts/ci/check_gateway_limits.py:248`：`PROXY_PASS_RE = ^\s*proxy_pass…` 只识别独占一行的指令。实测在 nginx.conf 加 `location /x/ { proxy_pass <url> }`（同一行）→ 检查器 rc=0 放行；写成独占一行则被拦。静态主机名会走宿主外部解析、也会直连外部。修复：对去掉注释后的全文按 `;`/`{`/`}` 切分指令再匹配（不锚定行首），`large_client_header_buffers`、`resolver` 等同类正则一并改；补“同行多指令”用例。
- **n1** `check_gateway_limits.py`：`limits.conf` / `limits.dev.conf`（`nginx.conf:52` 在 http 级 include）不检查 `resolver` / `proxy_pass` / `server`。http 级重复 resolver 会让 `nginx -t` 失败，风险低；建议规则 5 加“limits*.conf 只能出现 limit_req_zone / map / limit_req_status 等白名单指令”。
- **n2** 新增服务（非 nginx 名、同 nginx 镜像、host 网络）作为第二网关不在本规则范围，靠规则 7 服务白名单（check_secret_boundary）间接兜住，无需改。

## 3. 架构师裁定 A（运维实现）

nginx 加 **`proxy_connect_timeout 3s`**（server 级，覆盖所有变量形式 proxy_pass 的 location，含 `/health/live` 探针）。理由：内部网络连接应在毫秒级；T-O13 §2.3 实测 api 停掉后 `valid=10s` 缓存窗口内请求向旧 IP 发 SYN 挂起，最长 60 s（默认值），加后降到约 3 s，返回 502/504 走部署层统一错误页（与全局维护页同类，不进契约错误码表）。`proxy_read_timeout` 不变。运维同时：CI 规则 9 检查该值存在且 ≤ 5s；smoke / 演练复测“挂起 ≤ 约 3 s”。已登记 plan §1.3。

## 4. T-O13 演练报告结论（/workspace/team/reports/T-O13.md）

**plan.md 中没有 T-O13 的任务行或验收条件**（grep 无结果），升级门槛以 review-d1a148f ④ 为准，逐项对照：

| 门槛（review-d1a148f ④） | T-O13 证据 | 判定 |
|---|---|---|
| 停机演练记录 docker / compose 版本 | §1：aia-t01，Docker 29.9.2、Compose v5.6.1、nginx 1.31.2 | ✅ |
| 502 时长 | §2.1：出错约 54.4 s（502 约 44.9 s + 挂起约 9.3 s；窗口由 api 停机时长决定） | ✅（挂起部分由裁定 A 处理） |
| nginx 不重启 | RestartCount 0、StartedAt 不变 | ✅ |
| 恢复 ≤ valid=10s | api start 后约 4 s healthy | ✅ |
| 未知名字 < 1 s 失败 | 约 0.057 s SERVFAIL | ✅ |
| 无对外连接 | tcpdump、conntrack、ss 均确认 | ✅ |
| 写 T-O13 报告 | 已写 | ✅ |
| nginx_limits_smoke 真实运行 | §3：OK×26、FAIL×0、rc=0 | ✅ |
| 建议补 m1 / m2 | 666cd6e 已补（见上） | ✅ |
| 正式目标宿主重做 | §4 标 ⏳ | 未完成（上线门槛，不是升级门槛） |

**判定：满足升级门槛**（d1a148f + 666cd6e 可推送 / 用于升级测试部署）。**上线门槛尚未满足**：上线前须 ① 运维实现裁定 A 并复测挂起 ≤ 约 3 s；② 在正式目标宿主（生产 Docker 版本）重做停机演练与 smoke，补 T-O13 报告 §4 末行。

---
裁定登记：docs/plan.md 本地提交 1294476（未推送）——A 网关 `proxy_connect_timeout 3s`（运维）；B 主密钥多版本为上线门槛，新增后端任务 **T-B57**，重加密 CLI / 轮换流程放 V2（运维在 T-O12 之后跟进），契约不变；§9 问题 95（默认执行，用户可改，上线推迟一个后端任务的工作量）。
