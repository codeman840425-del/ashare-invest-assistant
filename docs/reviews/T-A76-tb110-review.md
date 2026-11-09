# T-A76 评审：be/T-B110（0030 门控事实清除 + 删除 CLI 修复）

> 架构师，2026-11-09（America/Denver）。评审对象 be/T-B110 = 3369d3b（a1800a0 B1、eb8f8b0 B2/B3、3369d3b B4），依据 docs/T-A73 = 1ea1227 上的 `docs/reviews/T-A73-0030-plan.md`。
> 文中行号均以 3369d3b 为准。0030 = `src/backend/migrations/versions/0030_ta73_purge_gate_facts.py`；CLI = `src/backend/app/cli/delete_user_data.py`；grants = `deploy/db/roles/grants.sql`。
> 改动规模（git 复核）：3 个文件，净 +220/−1（逐提交合计 +221/−2）。

## 0. 结论：**有条件通过**

函数本身的删除范围、回滚和迁移可逆性都核对通过，实测也通过。但 B1 的授权在部署后**会被 db-roles 覆盖反转**（问题 1），必须和运维 O1（T-O60）同批合入，并在 db-roles 重跑后复验，才能进 main。

合入条件：
- C1（阻断）：与 T-O60 的 O1/O2 同批合入；在 0030 库上**跑完 db-roles 之后**，复验 aia_api、aia_ingest 无 EXECUTE，aia_maint 有。
- C2：测试补齐 PG 行为用例（问题 2），先红后绿留档。
- C3：修 T-T24 测试夹具缺授权段（问题 3），使 T5 回归全绿。

## 1. 问题清单

| # | 严重 | 位置 | 问题 | 处理 |
|---|---|---|---|---|
| 1 | **高（阻断合入）** | 0030:40-45、93-98；grants:109、483、461-465 | 0030 只在迁移时 REVOKE PUBLIC、GRANT aia_maint。compose 每次 up 都在 migrate 之后跑 db-roles（`deploy/compose/docker-compose.yml:313-315`）：grants:109 对 ops 全部函数授 aia_api、aia_ingest EXECUTE；grants:483 撤掉 aia_maint 在 ops 的全部函数权限，而 grants:461-465 的白名单没有这两个函数。**已实测**：重跑 grants.sql 后 aia_api/aia_ingest = t/t，aia_maint = f/f；aia_api 能调 `ops.gate_user_refs` 读出任意用户的门控计数（借属主权限越过 ingest_private 的 RLS 与 T-O57 隔离），CLI 则因 aia_maint 无权限而失效。T-B110 的权限证据是在 db-roles 重跑之前采的 | 由 O1 修（排除这两个函数出通配、加入 aia_maint 白名单、自检）；C1 |
| 2 | 中 | `src/backend/selfchecks/test_tb110_gate_purge.py:15-49` | 3 个用例全是读源码的字符串断言，没有任何 PG 行为用例：非 purging 负例、`gate_scope_shared` 整笔回滚、跨用户行不受影响、db-roles 后的权限都没有自动化。另外 :33-36 依赖 `PYTHONPATH=.`，不设置时报 `No module named 'app'` | 测试按 T-A73 T3/T4 补用例；本次手工结果见 §3 |
| 3 | 中（既有问题，被掩盖） | `tests/backend/api_app/test_delete_user_data_cli_t_t24.py:80-83` | 夹具只套用 grants 的 `$maint$` 段，漏了 `$vendor_grant$`（grants:654-744）给 aia_maint 的 `market.master_vendor_batches` SELECT。基线上 4 例先因 ingest_private 报错；3369d3b 修好后，同一组里 3 例改报 `permission denied for table master_vendor_batches`。不是 T-B110 引入，但 T5「回归全绿」达不到 | 测试修夹具（同时套用 `$vendor_grant$`） |
| 4 | 低 | CLI:892-896；0030:76-83 | dry-run 只显示计数，不检查 scope 是否被他人绑定；实测共享场景下 dry-run 无阻断，`--execute` 才报 `gate_scope_shared` 并回滚 | 建议 gate_user_refs 多返回 shared 数，dry-run 列为阻断 |
| 5 | 低 | CLI:892-894、1248-1250 | 库停在 0029 时（代码已含 B4），dry-run 抛 `UndefinedFunction` 原始堆栈，带绑定参数；dry-run 路径只捕获 `PurgeRefusedError` | 建议捕获 `SQLAlchemyError` 只输出首行（与 :1290-1291 一致），或明示「需迁移到 0030」 |
| 6 | 低 | CLI:403-405、616-618 | `ruff format --check` 不通过（多一个空行、可合并的一行）；基线该文件是格式化过的 | 后端顺手 `ruff format` |
| 7 | 信息 | 0030:19、51 | `search_path = pg_catalog` 可接受：所有表都已全限定，只用到 pg_catalog 的函数和运算符，无动态 SQL。按惯例可写成 `pg_catalog, pg_temp`，把 pg_temp 显式放到最后 | 可选 |
| 8 | 信息 | 0030:14-19、47-51 | 函数属主 = 库属主 POSTGRES_USER（compose 下是超级用户），所以函数以超级用户身份运行并越过 RLS（两表 `relforcerowsecurity=false`）。函数体是静态 SQL，参数只有 uuid，没发现借属主权限越权的路径。若将来对两表开 FORCE RLS，purge 会静默删 0 行 | 建议 O2 的 verify-roles 断言两表未开 FORCE RLS |
| 9 | 信息 | 0030:64-74 | scope 范围包括「目标用户的绑定指向、但 origin 是别人证书」的 scope；只要没有他人绑定仍引用，就会被删。按「门控事实归属绑定」口径可以接受 | 记入待异源复核 |
| 10 | 信息 | 0030:76-88 | 检查与删除之间没加行锁。若此时 ingest 为他人新建指向同一 scope 的绑定，`DELETE scopes` 会触发外键错误、整笔回滚（失败即关闭）；CLI 本来就在停机维护时执行 | 接受 |

## 2. 逐项核对

**删除范围（0030:47-92）**
- 前置：`app.users.status='purging'` 才继续（:58-62）。purging 状态无法提交（CLI:19-22），所以只能在 CLI 的同一事务里生效。
- 范围：先算 scope_ids（:64-74）＝目标用户绑定指向的 scope ∪ origin 属于目标用户证书的 scope；再查是否有 `user_id IS DISTINCT FROM p_user` 的绑定引用（:76-83），有就抛错。
- 删除：只删 `bindings WHERE user_id = p_user`（:85）和 `scopes WHERE id = ANY(scope_ids)`（:88）。没有 JOIN 删除，也不走级联。`bindings.scope_id` 无级联（0029:22），是第二道保险；`bindings.user_id/licence_id` 的 CASCADE（0029:20-21）只会删目标用户自己的行。
- 证书在主线是软删（`app/licences/service.py:390、479`），origin 关联不会丢，不会留下归属不明的 scope。
- 未发现误删或越权删除路径。

**授权**
- 迁移刚完成时：两个函数 ACL 只有属主和 aia_maint；aia_api、aia_ingest 调用报 permission denied；aia_maint 对 ingest_private 无 USAGE（直接查表报 permission denied for schema），符合 T-O57。db-roles 重跑之后见问题 1。

**迁移**
- `down_revision="0029"`（0030:6）；0029 blob 仍为 05774fe，相对基线 diff 为空；heads 只有 0030。
- upgrade/downgrade 只建、删函数，不动表、不动行，不取表锁。

**CLI（B2-B4）**
- 两处外键扫描排除 ingest_private（CLI:650、742），原先报错的 :720 / :849 不再触发。
- 漂移守卫 `_ingest_private_user_fk_drift`（CLI:619-639）只读目录表，不计行数；实测多加一列指向 users 的外键会被列为阻断。
- 触发器白名单加入 0029 触发器（CLI:531-535），dry-run 不再列出白名单外的触发器。
- `--execute` 在删证书行之前调 purge（CLI:973-986），行数写入审计，审计里只有表名和行数。

## 3. 本次实测（一次性无网络 PG，用完即删）

环境：timescaledb 2.31.0-pg16，`--network none`，只通过 unix socket 连接，合成用户 A（目标）、B（旁观），用完删容器。

| 用例 | 结果 |
|---|---|
| 红：基线 CLI（=main 代码）在 0029 库 dry-run | 失败，ingest_private 权限错误 |
| 红：T-T24 在基线 | 4 例失败，`permission denied for schema ingest_private` |
| 绿：0030 + 3369d3b dry-run | gate 1/2；无白名单外触发器 |
| 绿：`--execute` 正常路径 | A 的用户、证书、1 条绑定、2 条 scope 删除；B 的行不变 |
| 负例：scope 同时被 B 绑定 | 报 `gate_scope_shared`，rc=1；users/licences/bindings/scopes 前后完全一致，A 仍为 approved |
| 负例：aia_maint 对非 purging 用户直接调 purge | `gate_purge_requires_purging_user` |
| 漂移守卫：ingest_private 多一列 users 外键 | dry-run 列为阻断 |
| 往返（带数据）0030→0029→0030 | 数据 md5 三次一致；`pg_dump -s` 一致（只差随机 restrict 令牌） |
| db-roles 重跑后的权限 | **反转**（问题 1） |
| selfcheck 3 例 | 设 PYTHONPATH 时 3 过，不设时 1 败 |
| T-T24 在 3369d3b | 7 过 3 败，均为问题 3 |

## 4. 待异源复核（风控类，收口交接时交新团队复核 Bot）

本队口径：架构师评审 + 测试先红后绿是合入门槛；下列各点另留异源复核。

| # | 来源 | 复核点 |
|---|---|---|
| R1 | T-B110 / 0030:47-92 | purge 删除范围：scope 并集口径（含问题 9 的跨 origin scope），以及共享即整笔回滚 |
| R2 | T-B110 / 0030:14-19、47-51 | SECURITY DEFINER 以超级用户属主运行并越过 RLS；search_path 固定为 pg_catalog |
| R3 | T-B110 + T-O60 / grants:109、461-465、483 | EXECUTE 只授 aia_maint、PUBLIC 撤销、db-roles 重跑后不反转；T-O57 不被破坏 |
| R4 | T-B110 / CLI:619-639、650、742 | ingest_private 被排除出外键扫描后，漂移守卫是否足以兜底 |
| R5 | T-A74 B1（docs/reviews/T-A74-rulings.md:43） | 发布资格：n_映射≥20 或 模拟交易日≥20，日历缺日不计 |
| R6 | T-A74 B2（:44） | 缺 horizon 的观测不进 n（RC5/降权输入） |
| R7 | T-A74 B3（:45） | G6 warn 经 ack 只留审计，不挡信号、不降权 |
| R8 | T-A74 B4（:46） | S-01 以 T+5 为主口径，资格计数取 T+5 complete |

## 5. 待补

- 运维 T-O60（O1/O2）的 diff 交来后补评，重点是问题 1 与 R3。
- 合入后由架构师在 plan 7.3 删除清单补上 ingest_private 两张表（T-A73 §5）。
