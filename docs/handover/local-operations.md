# 本地部署与检查（默认离线；操作前审批）

> 以下是接班操作说明，本交接任务没有执行启动、迁移、外部调用、建库或部署。现有数据库在通知迁移/回滚门槛修复前不得盲目运行up或upgrade head。

## 1. 前置与版本冻结
- 从被批准移交的现有工作副本开始；本手册不授权克隆/推送、远程登录或接管另一个账户。
- Docker Engine + Compose v2；后端Python≥3.12、uv；前端Node≥22与package.json声明的pnpm版本。镜像/依赖以锁文件和deploy固定配置为准，不自行追最新版。
- 只读核对（仓库根目录）：
```bash
git status --short
git rev-parse HEAD
git log --oneline origin/main..HEAD
```
- origin/main仅是本地跟踪引用，可能陈旧；本命令不联网、不代表远程已经确认。最终SHA填 `<TBD-final-main-sha>`；有他人WIP不清理、不打包、不误作候选。
- 配置模板是deploy/env/.env.example，实际配置在仓库外/被忽略文件；不要输出实际.env、compose完整解析配置、环境变量全集或服务凭据。
- 默认本地dev叠加层采用MAIRUI_MODE=replay。既有环境覆盖仍须运维私下核实；切换live不是普通启动选项，必须另获审批，保持唯一获准调用方与采集闭锁。

## 2. 安全检查命令（只针对本次交付）
```bash
# 契约静态检查，仓库根目录
uv run --no-project --with pyyaml==6.0.3 python scripts/ci/check_contract.py
# files模式：把占位路径替换为自己实际改动文件，可列多个；禁止扫出结果后复制敏感值
uv run --no-project --with pyyaml==6.0.3 python scripts/ci/secret_scan.py files <changed-file-1> <changed-file-2>
git diff --check
```
密钥扫描必须0阻断；发现疑似密钥只报告规则/位置并停交付，不粘贴值，不添加临时豁免。其他人的diff有问题则报告责任边界，不代改。

## 3. 定点开发检查
```bash
# 仅在需要准备相应开发环境时；安装可联网，先确认环境政策
(cd src/backend && uv sync --frozen --group dev)
pnpm -C src/frontend install --frozen-lockfile
# 后端静态示例：限定实际受影响文件
(cd src/backend && uv run ruff check app/notify)
# 前端解释模块示例（MSW/内存测试，不是后端联调）
pnpm -C src/frontend exec vitest run src/pages/p2n05-ai.test.tsx
# 前端typecheck：仅在任务授权时执行，不构建产物
pnpm -C src/frontend exec tsc --noEmit -p tsconfig.app.json
```
后端selfchecks常依赖独立PostgreSQL/Redis、网络隔离和固定测试身份。未核对fixture/依赖/清理责任时不要运行；获得专用隔离环境后，从src/backend用 `uv run pytest <explicit-test-file> -k <case>` 只跑相关用例。不要连接共享/生产库，不使用真实用户样本。实际通过数、未跑项和SHA由 `<TBD-test-freeze-sha>` 的报告填写；本手册不复用历史数字作新验收。

## 4. 启动与迁移（仅获批的新隔离环境或已完成预检的目标）
```bash
# 这些会启动服务、构建镜像或改变数据库，不是纯只读检查
# 先完成私有前置、备份及0025旧事件/回滚门槛确认
deploy/scripts/up.sh
deploy/scripts/compose.sh ps -a
```
- up.sh默认带build；服务链含数据库/Redis→migrate（alembic upgrade head）→Timescale策略→db-roles依赖与应用/网关，实际以当前compose为准；任何一次性服务失败要停止排查，不绕过依赖。
- 现有数据必须先备份，且不能把缺主密钥当全新部署。已有卷缺封装私钥应从可信备份恢复，不重新生成覆盖。
- 独立核验迁移元数据可在src/backend运行 `uv run alembic heads`、`uv run alembic history`；它们用于核对代码链，不等于数据库升级通过。连接隔离库后，获批才运行 `uv run alembic current`、`uv run alembic upgrade head`。
- 当前代码末段0020→0022→0023→0024→0025→0026，单一head=0026；0021不在活动链，不为补编号合入暂停迁移。收尾时核对是否有新迁移。
- 0025旧事件非空拒迁；0025 downgrade尚不可执行，0026降级refs保全待修。不要直接套用通用 `alembic downgrade` 命令回滚有业务数据的库。
- ACL必须在迁移到其要求的head后执行；旧revision缺列时授权fail-closed是预期。业务worker用aia_api、采集用aia_ingest、删除维护用aia_maint，不能把业务进程改成属主解决报错。
- `deploy/db/roles/apply-roles.sh`、`verify-roles.sh` 已存在；由运维通过当前compose的db-roles环境执行，禁止手工把口令写命令行。候选closeout.sh/新一键修复属于ops侧枝，必须先确认其已纳入获批提交，不假设main已有。

## 5. 健康、登录与备份
- 用compose ps核全部应有服务；随后在获准本地网关验证首页/登录/健康端点和实际角色负例，不只看容器启动成功。路径/端口从当前配置取得，使用 `<TBD-local-base-url>`，不硬编码个人地址。
- 注册默认closed；无本人approved账号时，create-admin是否实现是阻塞，不能按plan中的意图命令假定可用，不能擅自开放注册或转用测试密码。
- 备份入口 `deploy/scripts/db-backup.sh`；恢复演练见 `deploy/runbooks/database.md`。数据库dump、imports原始文件卷、匹配主密钥/证书封装私钥必须配套；密钥与dump分开、受控离线保存。
- 恢复会覆盖目标数据，必须选专用恢复库并确认批准；不在交接中执行。不要把 `down.sh -v` 当普通停止命令，它会删除数据卷。
- 收尾上线仍欠全服务健康、页面/登录、生产来源/ACL、备份恢复、带数据升降级等指定证据，准确范围由 `<TBD-release-gate>` 填写。
