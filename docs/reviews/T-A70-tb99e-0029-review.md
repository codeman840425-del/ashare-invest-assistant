# T-A70 评审：远端分支 tb-T-B99e（0029 迁移、ingest 停写同步、probes 限流识别）

> 架构师，2026-11-09（America/Denver）。只读评审，未改 src/tests/deploy，未起库，未调麦蕊，未碰用户电脑。
> 对象：origin/tb-T-B99e = 8c5746b，相对 origin/team-b（f82a83b）10 个提交；只读 worktree 在 8c5746b（detached）。
> 对照：integ/teamb-p3 头 9245973（下称 p3）、origin/main d32a3f6。行号：tb 分支文件按 8c5746b，`p3:` 前缀按 9245973。

## 结论：**有条件通过**（仅限「0029 迁移文件休眠入链」；全部应用代码提交本轮不吸收）

- 0029 可以平接在 p3 的 0028 上，入链后是单一 head 0029，不产生多 head。
- 0029 只新建 `ingest_private` 下的对象，但**也在已有表 `app.user_data_licences` 上加了触发器**，所以它不算「完全自成一体」。用户库已经执行过 0029，因此入库版本必须与库里已执行的内容逐字节一致，任何修正只能放到 0030。
- 0029 的 downgrade 一旦库里有数据就永久拒绝。用户库按 T-O45 已有一条活绑定，所以 T-A67 §10 的「4c 降到 0028」路径**作废**。
- 应用代码依赖 T-B99 基座。这个基座有 48 个提交（merge 7c4079d 及其祖先），p3 和 main 都没有，而且带着搁置项。8c5746b 还有一处风控语义倒退。所以这些提交本轮都不吸收。

## 1. 迁移链（关注点 1）

| 分支 | 0027 | 0028（revision / down_revision） | 0029 |
|---|---|---|---|
| origin/main | 有 | 无 | 无 |
| p3 | 有 | `0028` / `0027`（p3:src/backend/migrations/versions/0028_tb95_risk_override_active.py:6-7） | 无 |
| origin/team-b | 有 | 同上，内容与 p3 一致（`git diff` 无差异） | 无 |
| tb-T-B99e | 有 | 同上 | `0029` / `0028`（src/backend/migrations/versions/0029_tb99e_gate_bindings.py:5-6） |

- 0029 只由 9aa119f 引入，之后没有再改过。blob 为 `05774fed18ab70e4ff506c3178107d03b854d31c`，下文统称「入库版」。
- 叠加到 p3 后是 0027→0028→0029 的线性单链，不会出现多 head。main 只到 0027，所以 0029 必须排在 P3 之后。
- 需要同步改的测试：p3:src/backend/selfchecks/test_tb95_reset.py:62 写死了 `get_heads() == ["0028"]`，0029 进链后会失败。p3:src/backend/selfchecks/test_tb92_repairs.py:59 只断言 head 数为 1，不受影响。
- 不要带入 `app/db/base.py` 里 SCHEMAS 增加 `ingest_private` 的改动（9aa119f）。p3:src/backend/app/db/base.py:43 保持原样，env.py 的 `include_name` 就会继续忽略这个 schema，autogenerate 和 `alembic check` 不会把休眠对象报成漂移。触发器本来也不在 autogenerate 的比较范围里。

## 2. 可逆性与数据安全（关注点 2）

| # | 级别 | 位置 | 问题 | 处理 |
|---|---|---|---|---|
| M1 | 高 | 0029:87-92，0029:78 | 只要 scopes 或 bindings 非空，downgrade 就 `RAISE mairui_gate_facts_require_authorized_archive`。aia_ingest 对 scopes 没有 DELETE 权限，scope 行也没有任何删除路径，所以**一旦用过就永久不可降级**；错误信息里说的「authorized archive」在仓库里不存在。数据安全上是对的：拒绝降级，不丢数据 | 写入契约：0029 视为单向迁移。禁止为了降级而删行（同 T-A52 第 9 条的口径）。归档脚本另立项，需评审并经用户批准 |
| M2 | 中 | 0029:41-47 | `prune` 的 UPDATE 没有加 `detached_at IS NULL` 条件，每次调用都会重写**全部** scope 行（COALESCE 不会让行免于被重写）。scope 只增不删 | 在 0030 里加过滤条件，并给 scope 定保留期 |
| M3 | 中 | 0029:51-72，0029:65；certificate_bindings.py:81-82、104 | 触发器在 `user_data_licences` 的 deleted_at/paused_until/status 每次变化时都执行 prune；ingest 的每个事务也执行一次 prune。结果是 api 和 ingest 两个角色的事务对同一批 scope 行加行锁，存在写放大和锁等待 | 同 M2。在 0030 里改成只对受影响的 scope 做 prune |
| M4 | 中 | p3:deploy/db/roles/grants.sql:105-108 | 每次 up 都会把 `ingest_private` 的 USAGE、DML 和全部函数的 EXECUTE 授给 aia_api。现在只靠 RLS（0029:28-35，`current_user='aia_ingest'`）挡住数据行，与「只给 aia_ingest」的设计不符（T-A67 §8 已经预警） | 运维：在 grants.sql 里排除 `ingest_private`，并在 verify-roles 里增加 aia_api、aia_maint 对该 schema 的 permission denied 反例 |
| M5 | 低 | 0029:57-63 | CASE 先判断 `paused_until`：ip_limited 且只暂停 120 秒时，绑定只保留 120 秒，24 小时那一支走不到。删除后重新添加证书，可以绕过 plan.md「1 小时内 3 次」的升级规则（p3:docs/plan.md:406）。这与契约第 28 条「最多 24 小时」（p3:docs/api-contract.md:47）并不冲突 | 0030 时改成取 `GREATEST(paused_until, deleted_at+24h)`，由产品口径确认 |
| M6 | 低 | 0029:14-18 | scope 只保存 `origin_licence_id`，没有外键。删除用户后会留下孤儿 scope 行，用户删除清洗（plan 7.3）不会覆盖到它 | 0030 或用户删除 CLI 里补上清理 |
| M7 | 信息 | 0029:10-82 | upgrade 是一个事务。CREATE TRIGGER 和两条 FK 会对 `app.user_data_licences`、`app.users` 短暂持有 SHARE ROW EXCLUSIVE 锁。两张表都很小，按「先停进程、再迁移」执行，风险低。`gen_random_uuid()` 在 PG16 原生可用 | 无 |

## 3. 风控与门控语义（关注点 3）

- 0029 不涉及 `risk_control_settings`，也不涉及 0028 的降级守卫。§7.11.2 T-A52 的语义（p3:docs/api-contract.md:1240-1255）不受影响。
- 但回滚指引需要同步改。p3:docs/api-contract.md:1255 写的是「保持 0028」，而用户库实际已经在 0029。0029 入链后要改成：代码不得低于 2442b9d（team-b 的 f20fd83），**并且必须包含 0029 文件**；库保持 0029，不降级。
- 删除后的保留期：非冷却立即删除，冷却按 paused_until，没有截止时间的按 24 小时。这与契约第 28 条（p3:docs/api-contract.md:47）一致，例外见 M5。

## 4. ingest 停写同步与 probes 限流识别（关注点 4）

| # | 级别 | 位置 | 问题 |
|---|---|---|---|
| C1 | 高 | src/backend/app/ingest/shared_gate.py:32-51；src/backend/probes/common.py:294-302、365；src/backend/selfchecks/test_tb99_gate.py:139-140 | 8c5746b 之后，`limit_code` 只认 HTTP 状态码和 `code`、`error_code`、`status` 字段。`{"error":"103:…"}`（HTTP 200）、纯文本 103 和「最多允许2个不同IP」都不再触发共享闩锁，测试还把这些写成了「不应触发」。这与 p3:docs/plan.md:400、p3:docs/plan.md:2309（「先查 body 的 error」）以及现有分类器 p3:src/backend/app/ingest/upstream.py:38、62 相矛盾，等于 fail-open。防止财务数字（如 103.0）误报的初衷是对的，正确的修法是像 upstream.classify 那样只解析 `error` 字段开头的错误码，不能把这条路径整个删掉 |
| C2 | 中 | src/backend/app/ingest/daily_lists.py:378-401、85；src/backend/app/licences/service.py:128-135 | 发送方在 HTTP 请求期间一直持有 DB 事务和 advisory lock（socket 超时 20 秒）。这段时间里，api 的暂停、删除或替换证书请求会被阻塞，库里还会留下长时间 idle 的事务 |
| C3 | 中 | src/backend/app/ingest/send_control.py:36-73 | flock 临界区只在 POSIX 上可用，非 POSIX 平台直接闭锁拒绝。要求所有写入方使用同一 UID 和同一个物理目录，T-B99e.md:14 自己也写了部署前要复核。现在用户电脑的部署形态与这个前提是否吻合，还没有核实 |
| C4 | 中 | src/backend/app/ingest/live.py:42、src/backend/app/ingest/shared_gate.py:55、src/backend/app/master/daily_delivery.py:40 | 依赖的 T-B99 基座带着搁置项：外部出口探测 `<host>`，以及名单 `DAILY_HTTP_LIMIT=3`。p3 根本没有 shared_gate.py、verification.py 或 live.py，这些应用提交没法单独拣入 |
| C5 | 低 | docs/handover/team/reports/T-B99b.md:15、T-B99c.md:15、T-B99d.md:14、T-B99e.md:13 | 里面有本机 Windows 路径（`<path>`），入库前必须脱敏 |

## 5. 逐提交吸收清单（关注点 5，有选择地吸收）

| 提交 | +/- | 结论 | 理由 |
|---|---|---|---|
| c1a1cbd | 801/45 | 不吸收 | 依赖 T-B99 基座（verification、shared_gate、live）；含 C4 |
| b0db492 | 20/0 | 可吸收（只作记录） | 纯报告。和代码一起入库更好；如果单独入库，要脱敏，并注明对应代码未合入 |
| a41794b | 3/3 | 可吸收（只作记录） | 同上 |
| 3322aff | 986/103 | 不吸收 | 依赖基座；licences/service.py 的 lock_control 与 C2 是同一个设计 |
| 0b18026 | 18/0 | 可吸收（只作记录） | 同 b0db492，需要脱敏 C5 |
| d85e660 | 430/17 | 不吸收 | 依赖基座 |
| e3c990b | 18/0 | 可吸收（只作记录） | 同上，需要脱敏 C5 |
| 9aa119f | 1365/231 | **拆分**：只吸收 `0029_tb99e_gate_bindings.py`（有条件），其余 16 个文件不吸收 | 0029 用来解决用户库在 0029、代码却缺这个文件的问题；其余文件依赖基座 |
| 0239895 | 17/0 | 可吸收（只作记录） | 同上，需要脱敏 C5（第 13 行） |
| 8c5746b | 71/20 | 不吸收 | C1 语义倒退；p3 的 probes/common.py 没有 shared_gate 接口，也拣不进去 |

**0029 入链的条件（全部满足才推送）**
1. 后端：用 `git show 8c5746b:<0029路径>` 取出文件，单独提交（commit 信息注明 `(cherry picked from 9aa119f, migration only)`），内容逐字节等于入库版（blob 05774fe）。同一提交里把 p3:test_tb95_reset.py:62 改成断言 head 为 0029、0028 在主链上。不改 base.py SCHEMAS，不带入 ingest_gate.py。
2. 运维：完成 M4 的 grants.sql 排除和 verify-roles 反例。
3. 测试（隔离 PG，只用合成数据）：空库 0028→0029→0028→0029 往返，`pg_dump -s` 结果一致；有 scope 行时 downgrade 被拒、库保持 0029；软删除证书后绑定按 M5 口径设置 expires_at；tb95 22/22；`migration_check` 输出 `0029 (single mainline head)`。
4. 架构师：改契约 §7.11.2 第 9 条，按第 3 节的口径写入。M2、M3、M5、M6 立 0030 待办，等将来吸收门控代码时一起处理。

## 6. 用户电脑上未跟踪 0029 文件的收尾（关注点 6，修正原思路）

前提：P3 和 0029 已入链，并经用户批准推送和部署。每一步都要用户批准后由运维执行。

1. **先停 api、worker、ingest**（`docker compose stop`，绝不 `down -v`）。原因是 api 开着热重载，运行中移走或替换这个文件会立刻触发拒启。
2. 执行 `db-backup.sh`，再对备份做恢复演练（`db-restore.sh <dump> --db aia_restore_check`），记录 sha256。
3. 比对三项：
   - 未跟踪文件的 `git hash-object` 是否等于 `05774fed…`；
   - revision 和 down_revision 是否为 0029 和 0028；
   - **库的实际状态**：`alembic_version=0029`；`pg_dump -s -n ingest_private`、`pg_get_triggerdef`、`pg_get_functiondef` 的结果是否与入库版一致。只比对文件不够，库里实际执行的才是事实。
4. **一致**：把未跟踪副本**移到仓库外的备份目录**（部署验证通过后再删），同时清掉 `__pycache__` 里 0029 的 pyc，然后 ff 更新代码。这一步必须先移走副本，因为同名未跟踪文件存在时 git 会拒绝覆盖。之后确认 `git status` 干净，再启动服务。**不执行 upgrade**，库已经是 head。最后核对 `alembic current`、`alembic heads` 都是 0029。
5. **不一致**：不更新代码，保持冻结。
   - 只有注释或空白不同、库里的对象与入库版一致：按第 4 步处理。
   - 库里的对象与入库版不同：不得用入库版替换文件，不得 `alembic stamp`，不得 `down -v`。也不能用 downgrade 回退：守卫会拒绝，而通过守卫就得删绑定行，这是禁止的。由架构师以库里的实际对象为起点，写一个幂等收敛的 0030，在恢复演练副本上验证，用户批准后再执行。
6. 作废 T-A67 §10 的 4c（降到 0028），原因见 M1。

## 7. 机械整理

提交清单和 numstat 交给 DeepSeek（deepseek-chat）做成表格，再用 awk 复核：9aa119f 的删除行数 DeepSeek 算成了 201（实际 231），合计也算成了 3729/389（实际 3729/419）。本文采用复核后的数字。评审判断由架构师完成。
