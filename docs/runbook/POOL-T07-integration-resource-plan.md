# POOL-T07：integration固定路径参数化与第二梯设施方案

北京时间2026-11-11。基线`origin/main=465e020`；代码冻结`34ec476fedcb448a6d14c80821251cbbc081419f`，分支ds/T07；本单不启动容器、不连接PG/Redis、不重跑历史取证、不操作用户栈。

## 已实现：T-B63专用PG身份参数化

`tests/backend/integration/tb28_isolation.py`保留历史默认身份，增加三个非凭据环境参数：

| 参数 | 语义 |
|---|---|
| AIA_TB28_PG_CONTAINER | Docker inspect的完整容器名（含开头`/`） |
| AIA_TB28_PG_SOCKET | Linux宿主与容器相同位置的规范化绝对Unix socket目录 |
| AIA_TB28_PG_VOLUME | 专用PostgreSQL命名卷名 |

新runner要么三个都不设置沿用历史固定身份，要么全部显式提供；空值、局部覆盖、路径穿越、Windows路径、非法名称直接拒绝。参数不构成资源授权，不能因能填参数就连接其他数据库。

资源验证仍只运行`docker ps -aq`和限定字段`docker inspect`，不读容器环境/密码、不启动停止或销毁。目标必须running、`network=none`、无ports；仅允许socket双向同路径bind与`/var/lib/docker/volumes/<指定卷>/_data`→`/var/lib/postgresql/data`两项精确挂载；与其他容器同源或父子目录共享也拒绝。Docker不可用保持失败，不静默跳过或走localhost回退。

`test_tb63_signals.py`把同一参数化socket交给原`tb60 --socket-dir`，不改业务/tb60库名/回滚断言。`verify_isolated_pg()`无参调用保持兼容，供原历史适配器替换；全局旧适配器的正式复验仍是下述第二梯，不据签名兼容声明其已通过。

Windows仅对`test_isolated_pg_guard_writes_and_savepoint`添加skipif（Linux无此跳过）；其余纯逻辑29例照常执行。合成身份守卫31例也在Windows真实运行。此skip不算45条真实PG断言通过。

未来设施齐备后可按下列命令复验（**本单未执行**）：

```bash
# 由运维在经授权的独立Linux runner提供三个身份值；不要设置共享库DSN。
PYTHONPATH=src/backend python -m pytest tests/backend/integration/test_tb63_signals.py -q -rs -p no:cacheprovider
```

## 已验收范围

- Windows定点：`test_tb28_isolation_config.py`+`test_tb63_signals.py`，60 passed/1平台skip。
- Linux定点：仅`test_tb28_isolation_config.py`，31 passed/0skip。
- 守卫单元测试禁止真实Docker，并仅模拟inspect元数据。负例含6种局部覆盖、非法路径/卷/容器、错身份/停机/bridge/端口、错卷/错socket/额外挂载、同源/父源/子源共享，以及Docker失败不回显。
- 没有运行真实PG测试、全量测试体或coverage；本单不代表第二梯设施恢复。

## 第二梯：tt21/tt22 closeout适配器

`tt21_closeout.py`/`tt22_closeout.py`不是无副作用路径常量：导入会安装全局audit hook、改写psycopg/Redis入口；collection hook还可能CREATE DATABASE、执行资源改写后的tb60、写证据产物。因此本单不直接参数化它们并运行；原文件保持不变。

后续建议单独引入“纯配置解析→前置验证→显式install adapter”三层，禁止导入即改写全局。参数最小集合及验收如下：

| 固定项/位置 | 后续参数与拒绝要求 |
|---|---|
| OUT `/workspace/team/reports/T-T22-closeout-logs`及T-T21目录 | 显式artifact根目录；只允许指定新run子目录；存在同名关键证据拒覆盖；与workspace私有runtime隔离 |
| PG `/tmp/tb70-tb91-owned-socket` | 单一PG socket配置，所有connect白名单、DSN改写、audit与tb60重绑定必须取同一冻结值；仍拒非新建库/集群角色操作 |
| Redis `/tmp/tb91-owned-redis/redis.sock?db=15` | socket与DB分别配置，audit/Redis URL/清理prefix同源；仍只删除本次前缀，禁止真正FLUSH |
| resources.json硬编码两个container Id/name/task标签 | 由运维生成并签收的当次身份清单；逐项对照实时inspect的Id/labels/network/mounts，不只相信旧静态resources.json |
| 服务Unix socket文件类型 | Linux下要求存在且为socket；Windows从入口明确拒绝/对应pytest skip，不把普通文件当socket |
| collection时创建库/动态exec与夹具改写 | 提前列出库名/run prefix，审查fixture、授权角色、清理责任后才能显式启用；旧“已知缺口过滤”不得自动扩大 |

适配器参数化的权限负例必须证明：被拒身份时零connect/零CREATE/零Redis命令；不向共享或生产库试连；退出后没有全局猴补丁遗留到其他pytest会话。只改OUT或替换`/tmp`字符串不足以验收。

## 第二梯：历史取证与P2N10

- `test_tb58_replay_calibrated.py`已有`AIA_TB28_EVIDENCE_ROOT`，但默认历史`/tmp/tb63-replay-*`与旧SHA清单只针对失效取证。当前三项F0610–F0612被T-T22明确判无效而skip，本单不激活、不生成“新基线”让其绿；需单独裁定新的证据来源与哈希/许可/只读清理责任。
- `test_p2n10_loop.py`与`run_p2n10.py`已有`P2N10_ARTIFACTS`/适配器依赖，不能把它们当新独立runner。下单前须核其`tt21_closeout`导入副作用与Redis socket路径统一，不只修裸模块导入就运行。
- 16个后端selfcheck的固定Unix socket位于src/backend，超出本单tests/修改范围；复用本单的配置/边界原则仍须后端授权另派，不通过全局skip代替设施。

## 运维/后端/测试责任

运维：独立Linux network=none PG/Redis、专用卷/socket、身份标签和最小角色；明确资源创建/销毁所有权，无共享/用户数据。后端：核对schema/head与45项原断言、历史适配器重绑定边界。测试：先合成验证配置与拒绝分支，再冻结真实runner做定点复验；如设施不符明确阻塞，不写业务已通过。任何部署、迁移回滚、重启均另走编排者当次授权。
