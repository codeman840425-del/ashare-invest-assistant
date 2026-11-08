# T-A04 运维意见：plan 问题 52「证券主数据能否展示和再分发」

运维，2026-11-01（America/Denver）。依据：reports/T-A04.md §6、docs/plan.md §4.6 与问题 51/52、docs/api-contract.md、
deploy/ 现状（main b195ca6）。

**范围声明**：本文只谈运维和部署。交易所公开列表（上交所、深交所、北交所，及巨潮、AKShare 补缺）和麦蕊数据能否展示、
能否再分发，属于授权与法律问题，本文**不下结论**。**需要用户确认各来源的许可/使用条款**（交易所网站使用条款、
巨潮、AKShare 上游、麦蕊服务协议中的再分发条款）后，再决定下面哪些“建议”变成“必须”。

## 1. 现状（事实）

| 面 | 现状 |
|---|---|
| 对外暴露 | 网关只绑 `<host>:${NGINX_HTTP_PORT:-8080}`；`/securities/*` 全部 🔒（需登录），`/admin/securities/reconciliation` 🛡（管理员）。V1 自用，注册关闭。 |
| 批量可取性 | `/securities/search` 不分页、每次最多 50 条，`q` 最短 1 个字符；用代码前缀（如 `6`、`00`、`30`）多次查询即可枚举全市场名单。`/securities/{code}` 带弱 ETag。 |
| 网关限流 | `/api/` 统一 zone `aia_api` 20 r/s（按 IP），没有针对 search 的单独限额；枚举约 5,500 个代码只需几分钟。 |
| 网关缓存 | nginx 无 `proxy_cache`，不缓存任何 `/api` 响应；无 CDN。 |
| 应用缓存 | plan §4.6 用 Redis 只做任务锁；未见主数据响应缓存（如后端以后加，需同样遵守下文第 2 条）。 |
| 日志 | nginx access log 记 `"$request"`（**含查询串**，即 `q=` 搜索词和证券代码）、状态、字节数、UA、request_id；**不记响应体**。容器日志用 docker 默认 json-file，compose 未配 `max-size`/轮转。 |
| 备份 | `db-backup.sh` 用 `pg_dump -Fc` 整库：**含 `market` schema 的主数据、历史表、词条、`master_snapshots` 元数据**，以及 `security_reconciliation_diffs`（其中 `source_value` / `source_name` 是**麦蕊返回值**，带 `source_licence_id`）。 |
| 原始快照 | plan 定 `master_snapshots.raw_path` → `data/master/`，保留 90 天、每日清理；compose 目前**没有**对应卷（T-B52 交付时需要加）。 |

## 2. 运维意见

1. **缓存**
   - 网关继续**不缓存** `/api`；不上 CDN / 共享缓存。`SecurityProfile` 等响应混有“本人证书取到的麦蕊字段”，
     一旦进共享缓存就会跨用户泄露——这一点与许可结论无关，是隔离要求。
   - 建议后端对 `/securities/*` 响应带 `Cache-Control: private`（弱 ETag/304 不受影响）；请后端/架构师定。
2. **对外暴露面**
   - 维持“全部需登录、不开放匿名接口、不提供批量导出端点”；确认前**不要**新增公开（未登录）主数据接口或下载文件。
   - 生产域名开放前，网关上给 `/api/v1/securities/search` 和 `/api/v1/securities?q=` 加**单独限额**
     （建议起点：按用户/IP 5 r/s、burst 20，超限走现有 `<at>rate_limited` 429 信封），抑制脚本枚举；
     这是降低“事实上的再分发”风险的部署手段，具体数值请架构师定。V1 本机自用阶段可先不启用，作为上线前检查项。
   - `/admin/securities/reconciliation` 含麦蕊值，保持仅管理员可见，不进任何对外页面或报表。
3. **日志**
   - access log 不含主数据本身（不记响应体），但含搜索词和代码，反映用户关注的证券 → 按用户数据处理：
     建议给容器日志配 `max-size`/`max-file` 轮转（或 daemon.json 统一配），保留期与其他日志一致。
   - 要求后端日志**不**落整页列表/响应体（主数据、对账 `source_value`）；`master_bootstrap`/同步任务只记行数、sha256、来源 URL。
4. **备份**
   - 库备份含主数据与对账中的麦蕊值：备份只用于本系统恢复，**不对外分享、不作数据集给他人**；异地备份按现有加密/权限要求。
   - `data/master/` 原始文件可从交易所重新获取，建议**不进异地备份**、按 90 天清理，减少原始名单副本的扩散；
     T-B52 交付时我会在 compose 加专用卷并把它排除在备份清单之外（如用户确认许可后要求留档，再改）。
   - 恢复演练用的临时库/容器用完即删（现有 runbook 已如此）。
5. **网关层是否需要加限制**：需要，但范围限于第 2 条（search 单独限额、维持全部登录、不加匿名端点）。
   不建议在网关做按字段过滤或改写响应——字段范围（问题 51）由后端契约保证，`attribution` 由后端填。

## 3. 需要谁确认

- **用户（合规）**：确认交易所、巨潮、AKShare 上游、麦蕊各自的许可/使用条款，特别是：
  ① 交易所公开名单能否在本站展示给已登录用户（含好友小范围使用）；② 麦蕊值能否存进对账表并出现在库备份里；
  ③ 是否允许保留原始名单文件。确认前按 plan 问题 52 的现行做法：只展示问题 51 字段、带 `attribution`、只用交易所公开列表。
- **架构师**：search 单独限额数值；`Cache-Control: private` 是否写进契约。
- **后端（T-B52）**：bootstrap/同步日志不落整份名单；响应缓存（如有）只能按用户隔离。

## ③ 日志轮转（d0672e0）— aia-t01 应用前通知（2026-11-01 20:3x MST）
- **会有短暂中断**：在 aia-t01 上执行 `compose.sh up -d --no-build --force-recreate`，对全部常驻容器（nginx/api/worker/ingest/signal-rt/beat/postgres/redis）逐个重建，以便套上新的 logging 配置；**不重建镜像**，数据卷不动。预计中断几十秒：重建 postgres/redis 期间 api 不可用，nginx 重建期间端口拒绝连接；一次性任务（migrate/timescale-apply/db-roles）会按依赖重新跑一遍（幂等）。
- 主密钥、MAIRUI_LICENCE、`.env` 都不动。如果测试正在 aia-t01 上跑用例，这段时间的失败属于预期内。
- **应用结果（20:17 MST）**：部署克隆 cherry-pick 为 bfe6977，另加仅克隆的 3f0320b（克隆还保留 cooldown-purge 服务，主仓 6670b10 已删除，也给它套上锚点）。执行 `compose.sh up -d --no-build --force-recreate`，用时 25.6s，rc=0。
  - **实测中断**：每 0.5s 探测一次 `/health/live`，非 200 的区间是 20:17:25.7–20:17:47.6，约 22s；之后恢复 200。
  - **结果**：12 个容器（含 3 个一次性任务）的 LogConfig 都是 json-file `{"max-file":"5","max-size":"10m"}`，常驻容器全部 healthy。
  - **副作用（已知）**：这次没有重建镜像，但 worker/ingest/beat/signal-rt/cooldown-purge 原来跑在旧的无 tag 镜像上（2a9b079 / 61ce02b），recreate 后改用当前 tag `aia-backend:aia-t01`（a53950f，18:53 构建，api 本来就在用这个镜像）。

## ④ worker → aia_api：aia-t01 变更通知（测试请知悉，先写后做）

- 时间：2026-11-01 约 20:27 MST 起，预计 1 分钟内。
- 动作：部署克隆 cherry-pick 1f6965d（克隆内 118b1e4）→ `run --rm db-roles`（幂等授权，新增 $worker$ 段只是显式 GRANT + 自检）
  → verify-roles → **只重建 worker**（`up -d --no-deps --no-build --force-recreate worker`）。api / ingest / beat / signal-rt / nginx 不动，网关不中断。
- 影响：worker 重启约 10–20 秒；aia-t01 的 worker 镜像（a53950f）早于 6670b10，还是占位实现，不跑清理任务，对测试无可见影响。
- 结果（20:27 MST）：db-roles rc=0（NOTICE“worker（aia_api）所需 DML 已就位，无 DDL”）；verify-roles rc=0（68 OK / 0 FAIL）；
  只有 worker 容器 ID 变化，约 9 秒 healthy；容器内 `select current_user` = aia_api；网关探针 40/40 均 200（未中断）。
- beat / signal-rt 用到的表（只读核对 src/backend/app/workers，未改）：**都不访问数据库**。beat 只按 jobs.schedule 往 Redis 写
  `beat:due:*` 与 `jobs:worker` 队列；signal-rt 是占位循环（runner.run 无 tick）。两者目前仍继承 x-app-env 的属主 DATABASE_URL
  （未使用）；建议架构师裁定是否收掉（不连库则删 DATABASE_URL，或也改 aia_api）。
- 需要属主 / aia_maint 的 worker 任务：无。三项任务全部在 aia_api 的 DML 范围内（临时库已以 aia_api 实跑带数据验证）。

## ⑪ 预告（应用前写）：aia-t01 worker 挂 imports 卷

- 提交 5c76866（克隆 de87807）。将在 aia-t01 只重建 worker（`up -d --no-deps --no-build --force-recreate worker`），
  其余服务不动；预计 worker 不可用 ≈10 秒，期间到期清理任务排队，不影响 api。
- 回滚：克隆 `git revert de87807` 后同样只重建 worker。
- 结果：worker 重建后 6 s healthy；容器内 uid 10001，`$IMPORT_STORAGE_PATH`=/var/lib/aia-dev/imports 属主 10001、700，
  可写（touch/rm 探针）；挂的是与 api 同一个卷 aia_imports（rw=true）；/health/live 200。selftest 644 passed。

## ⑴ aia_maint 禁读补验（T-O11 aia_deny 裁定）

- 提交 94cddd8（克隆 b4ba82c）：grants.sql 第 16 行注释改正（aia_deny 只有一处）；verify-roles 加 aia_maint 读
  target_ciphertext / response_body / cooldowns.fingerprint 的 permission denied。aia_api 不加列级禁用（按裁定）。
- aia-t01 重跑 verify-roles：**71 OK / 0 FAIL**。架构师预期 57 = 原有 54 + 本项 3；实际总数还含 ④ 第 6 节 14 项
  （worker/aia_api：7 项 DML 可用、2 项拒绝、3 项 DDL 拒绝、2 项属性检查）→ 54 + 14 + 3 = 71。

## ⑤ + ⑥⑦ 预告（应用前写）：aia-t01 网关搜索限额 + 上游连接超时 + 502/504 统一错误页

- 提交：⑤ f6c36ec（证券搜索 aia_search 5 r/s、burst 20；`/securities/*` 与网关错误信封带 `private, no-store`），
  ⑥⑦ efb53b8（server 级 `proxy_connect_timeout 3s`；网关自产 502/504 → JSON 信封 `GATEWAY_UPSTREAM_UNAVAILABLE` /
  `GATEWAY_UPSTREAM_TIMEOUT`，部署层统一错误页，不进契约错误码表；`proxy_read_timeout` 不变）。
- 动作（2026-11-01 约 20:5x MST）：克隆 cherry-pick 两项 → **只重建 nginx**（`up -d --no-deps --no-build --force-recreate nginx`），
  预计网关端口拒绝连接约 5 秒；随后**停 api 约 30 秒**测挂起时间（这期间 `/api/*` 返回 502/504 属预期），再启动 api 并确认 `/health/live` 200。
- 测试请知悉：aia-t01 挂的是 `limits.dev.conf`（aia_search 1000 r/s），搜索在 aia-t01 上**不会**按 5 r/s 限流；5 r/s 只在生产 `limits.conf`（smoke prod 段已验证）。
- 回滚：克隆 `git revert` 两个克隆提交后同样只重建 nginx。
- **结果（20:40–20:41 MST）**：克隆 337834d（⑤）、c53ca17（⑥⑦）。只重建 nginx：只有 nginx 容器 ID 变化，`/health/live` 第 2 次探测即 200
  （约 1 秒）；`nginx -T` 里有 `proxy_connect_timeout 3s`、`error_page 502/504`、`zone=aia_search`（dev 1000r/s）。
  - **停 api 测挂起**（20:41:03 停，20:41:18 启）：t+0（resolver 缓存窗口内）`/health/live`、`/securities/search`、POST `/auth/login`
    都是 **502，耗时 1–2 ms**，t+3…t+15 每 3 秒一次同样 502、≤ 2.3 ms；都走统一错误页（`GATEWAY_UPSTREAM_UNAVAILABLE`、
    `application/json`、`Cache-Control: private, no-store`、X-Request-Id 与 body request_id 一致）。
    api 再启动后约 3 秒 `/health/live` 200，其余服务未动、全部 healthy。
  - 解读：本机 docker 停容器后旧 IP 立即释放，连接被立即拒绝，所以挂起只有毫秒级；**`proxy_connect_timeout` 的 3 秒上限针对的是
    “IP 在但不应答 SYN”的情况**（跨主机网络、宿主防火墙丢包等），smoke 用黑洞上游实测 **504、挂起 3.004 s**。
  - 正式目标宿主重做 T-O13 停机演练时复测这两种情况（见下“上线前检查项”）。
