# r2 落盘到用户本地栈：部署链预演清单（O-07）

2026-11-11，北京时间；本次只交付文档，未复制在写产物、运行策略、建库、备份、迁移、部署或重启。第三批 O-07 的范围以本清单为准；此前“重启执行＋栈版本核对”的同号候选不据此启动，宿主窗口仍按 O-06 另派。

本预案基于 `origin/main=465e02046fa8d971897603742497444f884e89a2` 的部署脚本，以及冻结 r2 分支 `a782a1e` 的 writer 静态阅读。所有待验收项初始均为“待执行”；历史部署版本 7e167f7/迁移0027不是本次目标版本，当前开发线迁移头也不能直接当作用户栈实况。

## 一、准入链与交接责任

| 阶段 | 责任人 | 必须交付的证据 | 不满足时 |
|---|---|---|---|
| r2 完整结束 | 后端执行会话 | 自然退出状态、最终阶段/完整窗口记录、冻结源码SHA与配置/输入身份、三件套路径 | 继续等待；心跳、部分checkpoint不代替完成 |
| 持久归档 | 后端确认源，运维协助 | 新目录副本、逐文件SHA256/字节数清单、源/副本一致和完整标记 | 保留源与失败副本，不宣称归档完成 |
| 独立终算 | 复核 | 同一冻结三件套的独立复算、时序/费用/缺证结论 | r2不放行 |
| R1–R5 核验 | 测试 | 冻结身份、对应节点结果、权限/失败负例及未覆盖项 | 修复后重新核对应冻结对象 |
| T-R66/R67 判读 | 研究员 | 五窗口/P1–P10/红旗判读、保留集及来源等级限制 | 不能以runner内建verdict代替独立结论 |
| 部署候选冻结 | 编排者 | 获准PR/提交清单、最终合入main的SHA、必要定点证据、双扫0、唯一迁移头 | 未合分支或未终核不列部署候选 |
| 本机维护准入 | 编排者统一对用户 | 目标本地栈、停写/回滚范围、维护窗口、已批准执行单 | 本文不启动执行 |

r2 研究结果归档与产品版本部署之间没有自动导入、自动改策略或自动批准关系。原始行情、结果三件套、证书、账户与凭据不入Git；只有脱敏结论和获准代码进入候选。部署通过也不等于G7审批、真实麦蕊调用或策略上线通过。

## 二、三件套冻结与持久归档

冻结writer见 [outputs.py（冻结a782a1e）](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/outputs.py#L248)：成功发布为 `trials.csv`、`legs.csv`、`summary.json`，先写同文件系统临时目录再rename发布；失败发布为独立 `.failed` 目录。对应源码可能尚未合入main，执行时以已批准冻结分支内文件及A-08自描述文档为准，不从最新branch tip补充字段。

1. 后端明确完整run的绝对路径、执行源码SHA、配置及输入摘要、起止时间和进程退出状态。不得读取在写输出作为终版、不得删除publishing锁、不得把preflight/failure.json或checkpoint改名凑三件套。
2. 后端确认源静默后，运维将完整run及关联冻结证据复制到 `F:\workspace\team\probes\` 下新的唯一子目录；保留原件，不移动、不覆盖同名旧副本。拒绝符号链接/重解析点、路径越界和源路径身份不符；任何补件另建新版本副本。
3. 先做获准的本地敏感信息扫描并确认0命中，不打印原始响应或凭据；逐文件核相对路径、大小、SHA256，写 `evidence-copy-manifest.json`。清单记录源码/配置/输入身份及扫描结果，全部源/目标核对完成才写 `complete=true`。复制前后源摘要必须不变，变化即撤销“完整”判断并重新冻结。
4. 可解析三文件不等于语义通过；行数、枚举、时间窗、单位、空值和保留集身份由复核/测试按冻结schema核验。大文件校验耗时依大小决定，不以摘要缺省或只抽样冒充逐文件一致。
5. 将受控目录与清单摘要交复核、测试、研究员；仓库报告仅写脱敏状态/摘要，不贴真实逐腿数据。

仓库外 `F:\workspace\team\probes\REBUILD.md` 提供“先扫描→新副本→逐文件哈希→完整标记→再汇报”的归档原则。其 `probe_runtime.py archive` **专用于探针results路径并要求麦蕊扫描凭据**，不能直接拿来归档r2，也不能为归档重新索要或注入麦蕊凭据。执行单应明确r2适用的复制/扫描入口；未有经核准入口时保留源并报编排者，不以探针工具绕过路径限制。本单没有编写或执行归档器。

## 三、部署前冻结旧栈与停写（回退点 R0）

- [ ] 编排者签署目标本地栈与执行权限，主工作副本属于运维可操作的干净main；本仓库共享主树若有他人WIP，停止，由原责任人/编排者处理，不替人stash、切分支或提交。
- [ ] 在代码更新前记录旧main SHA、现有容器镜像ID/固定digest、compose项目及卷前缀、WSL身份、已生效配置摘要、数据库实际迁移版本和服务状态。只选必要字段，不输出环境全集、实际.env、DSN或完整docker/compose配置。
- [ ] 保存可恢复的旧代码工作副本/镜像和受控配置；镜像tag会被重新构建覆盖，应保留旧镜像ID及实际可重建的固定输入。密钥原件保持，imports卷与dump成套备份，主密钥/证书私钥分开受控保管。
- [ ] 先进入明确的停写窗口：后端确认在途事务/队列已安全结束，暂停用户写入及所有会写库/文件的worker、beat、ingest、signal-rt等生产者。不能只停API漏掉后台写入，也不以杀进程中断事务代替收尾。保留Postgres供备份，其他组件按已批准顺序处理。
- [ ] 停写后再更新代码。dev叠加层将源码只读挂载给API及后台服务，API带reload；ff-only本身可能改变运行行为，不能假定到closeout deploy才生效。
- [ ] 使用与当前栈一致的WSL发行版/运行身份；不用Windows Git Bash调用部署。项目/卷/密钥目录取自已存在的本机配置；配置缺失即停，不让compose自动生成另一套配置/口令。
- [ ] 有足够空间同时保存源库、恢复校验库、dump、imports备份和旧镜像；所有版本/权限条件先核验，访问拒绝即停，不扩权或换属主绕过。

## 四、受控更新与部署步骤（均仅供执行单使用）

以下在已批准的WSL项目根执行。命令分成不同闸门，**不可整页粘贴连续运行**。任何非0或身份不符均停止；复核/测试的先前通过只对冻结SHA有效。

### D1：fetch 与 ff-only

```bash
set -euo pipefail
: "${APPROVED_MAIN_SHA:?set the approved full main SHA}"
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"
git fetch origin
test "$(git rev-parse origin/main)" = "$APPROVED_MAIN_SHA"
git merge --ff-only origin/main
test "$(git rev-parse HEAD)" = "$APPROVED_MAIN_SHA"
git rev-parse HEAD
```

人工前置：分支必须main、工作区/索引干净；`origin/main`须等于执行单获准SHA，fetch后若远端已变则停在merge之前。merge后再次比对HEAD；不合task tip，不reset/rebase/amend共享历史，不强推。原数据库尚未迁移，保持停写；此处失败可返回已保存旧代码/镜像，无须触碰数据库。

### D2：备份与恢复到新校验库（回退点 R1）

```bash
deploy/scripts/db-backup.sh
```

保存本次准确dump路径、同名meta的SHA/大小/PG/TimescaleDB版本。不要按“目录最新文件”猜目标。核dump/meta一致，记录停写时源库迁移版本、用户数、用户表数；imports卷以同一静默窗口做受控副本，匹配既有主密钥及证书私钥。全部敏感副本只在仓库外或忽略目录安全保存。

```bash
# 由操作者预先设置本次已核验的dump和全新、唯一校验库名；禁止默认指向业务库。
: "${VERIFIED_DUMP:?set the verified backup path}"
: "${RESTORE_CHECK_DB:?set a fresh validation database}"
deploy/scripts/db-restore.sh "$VERIFIED_DUMP" --db "$RESTORE_CHECK_DB"
```

使用 [db-restore.sh](../scripts/db-restore.sh) 的默认串行恢复；目标库名事先确认不为业务库且不存在，**不加 `--drop-existing`**。PG主版本一致、TimescaleDB完全同版，meta缺失或损坏本次不得豁免。恢复失败保留现场，未验备份不得进入D3。

源库与恢复库分别经已有授权只读连接执行以下核对，值只写受控记录：

```sql
SELECT version_num FROM public.alembic_version ORDER BY version_num;
SELECT count(*) AS users_count FROM app.users;
SELECT count(*) AS user_table_count
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_schema NOT LIKE '_timescaledb%';
SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';
```

版本、用户数、同口径用户表数须与静默源库一致；schema清单及关键表计数按执行单补充，不能用计数相等证明逐行业务一致。TimescaleDB扩展/策略、imports对应文件可读性及密钥配对按 [数据库手册](database.md) 验证。记录恢复脚本退出码与预期告警范围；任何非预期错误即停，不只看日志最后一句“完成”。

基线465e020的备份脚本尚无O-03轮转参数，不能假定 `--protect`/`--rotate` 已可用。若执行候选合入O-03（#40），仅按其已验参数将R1备份标为保护点，保持默认dry-run；本单及部署窗口不授权真实轮转删除。closeout还会再备份，不让后一次备份替代已演练的R1。

### D3：部署并核内建检查（数据库变更点 R2）

```bash
AIA_PROFILE=dev AIA_CLOSEOUT_DEPLOY=1 deploy/scripts/closeout.sh deploy
```

默认replay，执行前私下核生效模式与无真实调用条件。live不是启动菜单，不因r2通过开放真实麦蕊或恢复已删触点。若执行单要求与dev不同的组合，应先由编排者明确；不能临场切live。

实际 [closeout.sh](../scripts/closeout.sh#L437) 的deploy顺序是：再备份→up→容器内verify-roles→nginx配置→HTTP→八服务健康；[up.sh](../scripts/up.sh) 已包含build/迁移/Timescale策略/角色应用/等待。不要额外先跑一次upgrade。deploy模式**不核准候选SHA、不消费accepted.manifest作版本准入、也不自动回滚**，D1/D2及下节验收由执行人补齐。

up内迁移或后续任何步骤失败，从R2处理，不能因为closeout非0就认为库未变。确认迁移图唯一head与目标代码一致，并将数据库实际版本对照目标head；不硬编码旧0027，也不盲信当前开发线0034。

## 五、部署后验收与恢复写入（回退点 R3）

| 检查 | 合格依据 | 验收边界 |
|---|---|---|
| 代码/镜像/迁移 | 获准HEAD、容器镜像ID、实际bind mount根一致；库版本等于目标唯一head | dev挂载会覆盖镜像源码，不能只看镜像tag |
| 基础设施/服务 | 八常驻服务api/worker/ingest/beat/signal-rt/nginx/postgres/redis健康；一次性迁移/角色步骤成功 | healthy不代替业务与ACL正确 |
| HTTP | closeout内建首页、login、health/live=200；另验health/ready符合契约 | live只证明存活，ready验证依赖；不打印登录凭据 |
| 权限/隔离 | verify-roles通过；按获准定点案例做未认证401/无权403/不可见404负例与允许路径 | 使用专用测试身份，不改属主修失败，不操作真实交易记录 |
| 版本相关功能 | 仅复测本次合入范围的真实HTTP/UI链；例如路由有无、null空态与版本跳转 | fixture演示不冒充已读取真实行情，不自动触发采集 |
| 数据保留/文件 | 升级前后用户与关键表差异符合迁移说明；imports可访问，密钥仍配对 | 单看表数相等不充分，schema变化单列解释 |
| r2证据/边界 | 归档清单SHA不变，独立终核链接在位；replay/G7/真实调用边界仍保持 | 部署不改原始三件套与策略审批状态 |

验收期间继续控制写入；需要测试写操作时仅限获准合成身份并留痕。全部通过后由编排者批准恢复生产者/用户写入，记录恢复时间。若部分服务已在up阶段恢复写入，必须记下范围及期间增量；不能对外宣称整个窗口零写入。

## 六、失败与回滚决策表

| 发生点 | 立即动作 | 恢复依据与签署 |
|---|---|---|
| R0/D1：未改数据库 | 保持停写，保留错误及旧/新SHA | 用R0已保存旧代码/镜像恢复原栈；不reset共享main，不动数据卷 |
| D2：dump或校验恢复失败 | 不进入D3，不替换业务库，保留失败校验库 | 业务库未迁移时按R0恢复服务；备份校验重做须另记结果 |
| R2：迁移开始后或完成状态不明 | 停止后续动作，冻结所有写入，记录实际库版本/已完成步骤 | 禁止仅换回旧镜像；按已验证R1 dump＋imports＋原密钥恢复到新的恢复库/受控卷，校验后切换 |
| R3：验收失败且存在新增写入 | 隔离写入并保存失败现场/增量 | 编排者判保留/补偿增量及回退时间点，用户确认可能丢失R1之后写入；不得静默覆盖 |

数据库回退按 [db-restore.sh](../scripts/db-restore.sh) 恢复到新名字：旧业务库留作现场，**脚本拒绝覆盖主库，不能靠 `--drop-existing` 绕过**。新库恢复验证完成后，执行人按当次已审连接配置切换方案与旧代码/镜像配套启动，重做ACL、迁移版本、HTTP、文件配对验收。具体库切换/卷切换命令须在执行前针对目标栈审定；没有经验证方案就停机报编排者，不猜配置或直接downgrade。

绝不执行 `down -v`、删卷/删业务库、用新密钥替旧密钥、清数据凑迁移条件或用属主权限绕过ACL。失败不会自动触发回滚；回滚需执行人按上述已验证备份方案行动并记录结果，R1后新增数据的损失必须显式裁定。

## 七、执行签署单（执行时填写）

- 执行单/目标本地栈/窗口（北京时间）/执行人：待签署。
- r2三件套归档清单＋SHA、复核/测试/判读证据：待签署。
- 获准main SHA、旧SHA/镜像ID、目标迁移head、双扫结果：待签署。
- 停写范围/时刻、R1 dump及imports副本/恢复校验、密钥配对：待签署（私密位置仅本机记录）。
- D1/D2/D3退出码与失败步骤、部署后验收/是否恢复写入：待执行。
- 回滚触发/使用备份/新恢复库核验/增量裁定/最终服务状态：待执行。

DeepSeek 行：未用；部署/回滚与归档边界的文档核对不外包。
申请新任务：本预案交编排者验收；可接离线运维单，实际归档/部署/宿主重启按冻结证据和当次执行令接续。
