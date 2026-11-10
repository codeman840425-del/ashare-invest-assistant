# 本地部署与检查（默认离线；操作前审批）

> 以下是接班操作说明，本交接任务没有执行启动、迁移、外部调用、建库或部署。候选修复已通过，但0027维护窗口复验与用户审批未完成前不得盲目运行up或upgrade head。

## 1. 前置与版本冻结
- 从被批准移交的现有工作副本开始；本手册不授权克隆/推送、远程登录或接管另一个账户。
- Docker Engine + Compose v2；后端Python≥3.12、uv；前端Node≥22与package.json声明的pnpm版本。镜像/依赖以锁文件和deploy固定配置为准，不自行追最新版。
- 只读核对（仓库根目录）：
```bash
git status --short
git rev-parse HEAD
git log --oneline origin/main..HEAD
```
- T-O35及本次交接已确认合并/推送基线7e167f7，origin/main与用户电脑一致，迁移head=0027。本手册的新文档提交不在该已推送基线内；他人WIP不清理、不打包。
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
后端selfchecks常依赖独立PostgreSQL/Redis、网络隔离和固定测试身份。未核对fixture/依赖/清理责任时不要运行；获得专用隔离环境后，从src/backend用 `uv run pytest <explicit-test-file> -k <case>` 只跑相关用例。不要连接共享/生产库，不使用真实用户样本。已知结果见progress-board/README：T-O33报告7通过，T-A43在5a26d17候选抽2通过；这不是最终合并hash的全量验收。

## 4. 部署方法与迁移门槛
- **绝不 down -v：不得删除数据卷。** 部署方法按T-O35命令摘要记录；以下仅供接班者在获准目标执行，本任务没有执行。
```bash
# 先确认工作区无待保护变更，不覆盖他人WIP；在main分支执行
 git fetch origin
 git merge --ff-only origin/main
 deploy/scripts/db-backup.sh
 # 将<backup.dump>替换为刚生成备份，恢复到新的校验库，不覆盖业务库
 deploy/scripts/db-restore.sh <backup.dump> --db aia_restore_check
 # 核对恢复库版本、用户数、表数，校验失败即停；成功才继续
 AIA_CLOSEOUT_DEPLOY=1 deploy/scripts/closeout.sh deploy
```
- 目标基线7e167f7；部署前先备份，失败按已验证备份恢复方案回滚，禁止自动删卷/破坏现有数据。closeout本身还会再备份，并顺序执行up、容器内角色校验、nginx/HTTP及服务健康检查。
- 现有数据先备份；已有主密钥/证书封装私钥必须匹配，不能重新生成替代。
- 已知候选链0020→0022→0023→0024→0025→0026→0027，单一head=0027；0021仍不在活动链，不合入暂停迁移补编号。
- T-B92 d5a9a60已实现历史来源证明、unknown排除新投影与保留事实的可逆降级；旧键冲突条件拒绝，0027维护窗口复验仍待。不可直接套通用downgrade处理业务库。
- T-O33 5a26d17已通过：最小ACL在迁移要求满足后应用；worker=aia_api，采集=aia_ingest，注销=aia_maint，不能改属主绕过失败。正式范围以最新契约T-A43矩阵为准。
- closeout自检/部署闸门已静态审查，verify路径在db-roles容器；这不是执行部署的批准。此前T-A43没有执行部署脚本或部署开关。
- B2真实麦蕊调用/采集完成接线待用户批准；默认replay，不因隔离库恢复而开放真实外部调用。

## 5. 健康、登录与备份
- 用compose ps核全部应有服务；随后在获准本地网关验证首页/登录/健康端点和实际角色负例，不只看容器启动成功。路径/端口从当前配置取得，目标地址从获准本机配置读取，不在公开交接中记录主机/IP或隧道地址。
- 注册默认closed；无本人approved账号时，create-admin是否实现是阻塞，不能按plan中的意图命令假定可用，不能擅自开放注册或转用测试密码。
- 备份入口 `deploy/scripts/db-backup.sh`；恢复演练见 `deploy/runbooks/database.md`。数据库dump、imports原始文件卷、匹配主密钥/证书封装私钥必须配套；密钥与dump分开、受控离线保存。
- 恢复会覆盖目标数据，必须选专用恢复库并确认批准；不在交接中执行。不要把 `down.sh -v` 当普通停止命令，它会删除数据卷。
- T-O35报告已完成备份恢复校验、0027升级、ACL211项通过、8服务健康及页面/登录页/健康HTTP；未登录验证、未调用麦蕊。G7 交接当时待用户本人测试审批；T-A109 已修订代批条款（plan 2.5.13），正式晋级以用户 Windows 已部署实例为准。真实来源与交易时段提醒实测、带数据降级/再升仍待，不能宣称全部产品验收。
