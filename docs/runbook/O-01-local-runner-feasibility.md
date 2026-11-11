# O-01 Docker npipe 与本地 Linux runner 可行性（方案，不实施）

日期：2026-11-11，北京时间。代码对照基线 origin/main=465e020；历史问题依据 T-T29/T-T35。用途是为后续设施单选路，不代表已恢复集成测试。

## 1. 已证实与尚未证实

| 核查项 | 观察/证据 | 能得出的结论 |
|---|---|---|
| 历史 Windows npipe 拒绝 | T-T29-logs/commands.md §3；当时未启动容器 | 历史执行身份/上下文下失败；报告未保留足够的 pipe ACL 和 token 证据，不能追认具体 ACL 根因 |
| 本次 Windows Docker | context=desktop-linux；端点为命名管道；docker version 客户端/服务端均 29.4.0，退出 0 | 当前进程身份可连 daemon；不证明其他 Bot、受限会话或 Windows 服务账户有权限 |
| 本次 WSL Ubuntu | 普通 uid=1000；docker 服务端 29.4.0；socket mode=0660、uid=0/gid=1001，当前用户组含 1001 | 普通 WSL 身份已有 socket 访问权；无需本单提权或修改 ACL |
| 产品容器 | docker ps 返回 8 个 aia-local 服务 healthy | 仅说明当前运行状态；未重启、未写库、未执行 compose up |
| WSL 环境 | python3 存在；本次 PATH 未找到 uv、pg_ctl、redis-server；8 逻辑核、约 30 GiB RAM | Python/依赖及测试设施仍需准备；Docker 连通不等于 runner 或隔离 PG 已就绪 |
| GitHub CI | .github/workflows/ci.yml 的 backend/contract 均 runs-on ubuntu-24.04；contract 使用服务容器 | 现有仓库不是 self-hosted 接线；CI 的 TCP PG/Redis 不满足全部历史专用 socket fixture |

本次没有触发 npipe 拒绝，因此不执行 ACL 修复技能、不更改 docker-users/服务身份/pipe ACL。若另一个身份仍失败，另单采集该身份下的 context、端点、docker version 退出码、错误类别与最小组成员信息；不打印环境全集、Docker 认证配置或完整 inspect。

## 2. 不能混为同一问题的三层依赖

1. **daemon 通道**：Windows 命名管道能否被实际执行身份访问。本次可达，历史拒绝未复现。
2. **Linux 执行语义**：TB89 的 no_ip_network 仅准 AF_UNIX，固定 `/tmp/tb89-pg-socket`，要求 listen_addresses 为空；Windows Python 即使拿到 Docker 权限，也不能直接替代这一环境。
3. **专用夹具身份**：T-T21 借 TB70 的专用 PG+Redis socket 并核 mainline；TB63 的 tb28_isolation 固定了容器名、network=none、零端口、socket 和历史卷 Source，且禁止其他容器共享挂载。新建普通 PG 服务不会自动满足这些断言。

证据位置：src/backend/selfchecks/test_tb89_full_migrations.py:54–81；src/backend/selfchecks/test_tb70_replay.py:44–45；tests/backend/milestone/tt21_plugin.py:19–29；tests/backend/integration/tb28_isolation.py:6–34。

## 3. 方案比较与成本

以下人时/磁盘/内存均为规划估算，不是本次基准测试；不含测试业务失败返修与历史产物重建。

| 路径 | 适用性 | 首次成本估算 | 长期成本/限制 |
|---|---|---|---|
| A Windows 原生 runner + 修 npipe | 适合无 POSIX 依赖的静态检查；不能独立解决 Unix socket、fcntl、/tmp | 诊断身份/ACL 0.5–1h，服务接线另 1–2h | 每个服务 token/context 都要验证，Linux 专用测试仍需另一执行环境；不推荐作本单主路径 |
| B WSL Ubuntu 单次本地 runner | **近期推荐**；当前普通身份已连 Docker，适合定点 TB89/T-T21 验证 | 环境与锁版本对齐 1–2h；三类隔离设施设计/准备+验收 2–4h；1–2 vCPU、2–4 GiB RAM、5–10 GiB 临时盘 | 与产品 daemon、r2 共享资源；Docker socket 权限接近主机控制权，必须固定可信 SHA、最小测试范围，不能当独立安全边界 |
| C 专用 Linux VM runner | **常驻自动化推荐**；独立 daemon/卷/工作目录，减少误触产品栈 | VM 与 runner 固化 4–8h；夹具适配和恢复验证另 2–4h；2 vCPU、4–8 GiB RAM、20–30 GiB 盘 | 增加镜像更新和磁盘巡检；同宿主 VM 仍占 r2 CPU/内存，可待长批结束安排 |
| D GitHub ubuntu 托管 runner | 不占本机资源；现有 CI 已使用 | 专用 socket 夹具编排与流水线接线 3–6h | 托管额度、拉镜像/依赖网络时间；本单不估账户费率，也不触发全量/coverage |

B/C 若要成为 GitHub self-hosted runner，注册 token、服务账户、安装与工作流变更另单授权；本单没有注册、下载安装或启用 runner 服务。

## 4. 推荐落地顺序（交下一实施单）

1. 锁定待测 SHA，在 `.worktrees/<任务分支安全目录名>` 创建独立目录；记录 Linux Python、uv、锁文件与镜像 digest。venv/pytest/mypy 路径只引用存活目录，结束 remove+prune，不删分支。
2. 先仅用普通身份只读验证 Docker server/socket；失败保持原失败，不用 sudo、root、换账户、开放 TCP daemon 或 chmod 666/777 来放行。
3. 为 TB89 单独提供 network=none、listen_addresses='' 的临时 PG 和专用 socket；测试端通过只读/最小所需挂载共享该 socket；不映射宿主端口、不挂产品卷，不接产品 DSN。以 fixture 自建随机数据库并 finally 清理。
4. T-T21 独立准备 TB70 PG、Redis socket、测试库及 isolation/mainline 元数据；不得复用 TB89 库或产品服务。测试产物写持久证据目录，不能依赖已删除的历史 worktree。
5. TB63 单列测试夹具迁移单：由测试/后端共同把历史硬编码容器/卷身份变为可审计的任务专用标识，同时保留 network=none、零端口、专用卷无重叠与业务 schema 保护。不能重建历史卷指纹或放松守卫来追求绿灯。
6. 分别跑一个正例与负例：正确隔离设施可识别；缺 socket、错误容器/共享卷/业务库目标必须在 DB 写入前拒绝。随后仅跑受本次设施影响的定点用例，禁止整树/coverage。
7. 输出完整命令、固定 SHA、资源清单、日志、扫描、退出码、清理证明与未解决项。失败保留日志并停止，不连接产品库兜底。

当前 r2 长批占 6 核，实施时先由编排者确认资源窗口；建议单次执行 concurrency=1、最多 1–2 核，且不与 r2 同时开重型测试。该限制是方案建议，本次未设置任何运行资源。

## 5. 权限、验收与回收边界

- 本单只读 Docker/WSL 元数据、读代码并写文档；没有容器创建/重启、镜像拉取、数据库写入、权限更改或外部数据调用。
- 自动 runner 只运行受信任仓库/固定 SHA，不接收不可信 fork 代码；不注入真实数据源、模型凭据、生产 DSN 或 Docker 登录信息。
- WSL 方案下共享 daemon 是剩余风险，禁止 docker system prune、volume prune、down -v 或按模糊名称批量删除。实施单只回收其登记的临时容器/卷/socket，先核绝对路径与资源归属。
- 无 Docker 权限与无隔离设施须分别报失败，不能 silent skip 或让 runner 指向现有产品栈。验收通过仅代表指定设施/指定用例，不宣称 T-T35 第二梯全部清零。
- 本方案尚未实施；需要编排者另派设施落地单后才执行 §4。
