# 评审：T-O11（07a4e2b、47c4b9c）——aia_maint 角色、待清文件队列收权、APP_MASTER_KEY 走 secret 文件

- 评审人：架构师；日期：2026-11-01（America/Denver）
- 方式：只读。`git archive` 导出到 /tmp/rv-to11（HEAD 当时 = a8e055b；`git diff 47c4b9c a8e055b -- deploy scripts .gitignore` 为空，deploy 部分即 47c4b9c 的状态）。
  另起一组自己的容器 rv-to11-pg / rv-to11-redis（timescaledb 2.31.0-pg16、redis 7.4.12，digest 与 compose 一致），用完已删除；临时文件已清理；
  别的代理的容器（aia-t01-*、be-b03a-* 等）和工作区未提交改动均未触碰。
- 评审期间主仓库新增 07b8d74、0e31218 两个提交（其他代理），未评审，已列入推送顺序表。

## 结论

| 提交 | 结论 |
|---|---|
| 07a4e2b（T-O11） | **有条件通过**：没有 B 级问题；有 2 个 M 级问题（M1 由运维修，M2 需裁定，见下）；条件是推送时必须和 47c4b9c 一起推，不能单独推 07a4e2b |
| 47c4b9c（T-O11 补） | **通过**：偏差接受（理由见下） |

plan §7.3 裁定 C 的 ①–⑤ 中：
- ③（REVOKE 在整 schema 授权之后）、④（verify 断言）已在真库上验证；
- ⑤（dry-run 不用 aia_api）已在真库上验证，但 owner DSN 仍可跑 dry-run，见 m2；
- ② 运维这一侧（compose、secret、挂载）满足，但 CLI 仍会回落读取环境变量，属于后端问题，见 m1；
- ① 的“表级最小”满足，“列级最小”没做到，见 m3。

45589c2 已不再阻断推送：B1/B2 已由 8fd9502 修好，8fd9502 的运维前置也由本次两个提交补齐。**前提是 45589c2 必须和 8fd9502 一起推。**

## 偏差裁定：membership 撤销挪到授权循环之前 —— 接受

**检查结果**
1. `$grants$` 循环（grants.sql 82–139 行）里只有对象权限（TABLES、SEQUENCES、FUNCTIONS、DEFAULT PRIVILEGES，以及 ciphertext 列级处理），**没有任何角色 GRANT**。循环之后的 `$purges$` 和 `$maint$` 也没有。所以没有地方会把 membership 重新授出去。
2. `ops.pending_file_purges` 的 `REVOKE ALL … FROM aia_api, aia_ingest` 仍在 `$purges$`（141–162 行）里，位于 `$grants$` 之后。pending 表的 id 不是 serial，没有序列需要额外收权。
3. 文件末尾 `$maint$` 自检会再查一遍：没有 membership、`pg_has_role` 为 false。即使以后有人在循环里误加了角色授权，apply 也会失败，不会静默放行。

**为什么挪是对的（实测）**
用 07a4e2b 版的 grants.sql（撤销在循环之后），先 `GRANT aia_maint TO aia_api`，再执行。结果 `$grants$` 自检报 `aia_api 仍可 SELECT app.user_data_licences.ciphertext`，apply 中止，membership 留在库里。

原因：aia_api 是 INHERIT，aia_maint 对 app 全表有 SELECT，aia_api 经继承就能读 ciphertext。撤销必须先于这个自检执行。

**结论**：membership 和“对象权限会被整 schema 授权重新授出”不是一类问题，不受裁定 ③ 的顺序约束。挪到前面是必要的，而且没有副作用。

## 问题

### B 级
无。

### M 级

| # | 位置 | 问题 | 建议 | 负责 |
|---|---|---|---|---|
| M1 | deploy/scripts/compose.sh:105–107；app-master-keygen.sh | 已有部署如果还是从 `.env` 读 APP_MASTER_KEY，升级后第一次跑 compose.sh 时，脚本发现 secret 文件不存在，就会**静默生成一把新主密钥**。旧值被替换后，会失效的有：邀请码 HMAC、证书去重 HMAC、冷却指纹（seal.py）、登录 IP HMAC、分页游标、importing/keys.py 派生密钥。T-O11.md 第 89 行写了“升级前要先迁旧值”，但脚本不检查这一点。aia-t01 库是空的，所以这次没有出事。 | secret 文件缺失时，compose.sh 先检查 `.env` 或环境里是否有非占位值的 APP_MASTER_KEY：<br>• 有：拒绝生成并提示迁移步骤，或者在不打印的前提下把旧值写进 600 文件；<br>• 也可以加一道库检查：invite_codes、user_data_licences、users 非空时拒绝自动生成。<br>同时在 runbook 写明迁移步骤。 | 运维 |
| M2 | config.py:535（Settings 校验）；docker-compose.yml 中的 ingest、beat、signal-rt；check_secret_boundary.py 规则 7（`MASTER_OWNERS = ("api","worker")`） | `APP_ENV` 不是 local/test 时，Settings 要求必须有 APP_MASTER_KEY（实测 `APP_ENV=production` 不带主密钥时报 ValidationError）。ingest（workers/ingest.py:82）、beat 和 signal-rt（经 runner.py:32）都会调用 `get_settings()`，但都拿不到主密钥，所以**生产环境里这三个服务起不来**。这个问题 origin/main 上就有（以前也只有 api/worker 有主密钥），不是 T-O11 引入的；但 T-O11 的 CI 规则 7 把“只给 api/worker”固化了，以后要修会被 CI 挡住。maint-cli 不受影响（实测 production 下不带主密钥 dry-run 正常）。 | 架构师二选一：<br>(a) 后端把主密钥校验改成只在真正用到的服务上做（推荐：ingest、beat、signal-rt 不需要主密钥）；<br>(b) 给这三个服务也挂上主密钥，并同步修改规则 7。<br>上生产前必须解决，不阻断推送。 | 架构师裁定 → 后端 / 运维 |

### m 级

| # | 位置 | 问题 | 建议 | 负责 |
|---|---|---|---|---|
| m1 | delete_user_data.py:845–855 `_maint_url()` | `_FILE` 不存在时会回落读取环境变量 `AIA_MAINT_DATABASE_URL`（实测可用），违反裁定 ②“只从 `_FILE` 读”。compose 一侧有 CI 规则挡住，但 CLI 自己不拒绝。 | 删掉这个回落，只认 `_FILE`，并补一条测试 | 后端 |
| m2 | delete_user_data.py:858–873、937–946 | dry-run 只拒绝 aia_api、aia_ingest；用 owner DSN（`DATABASE_URL`）仍可运行（实测可用）。虽然在只读事务里执行、不会写库，但裁定 ⑤ 写的是“aia_maint 或只读角色”。 | dry-run 也只接受 aia_maint 或只读角色，或者至少拒绝 rolsuper 和对象属主 | 后端 |
| m3 | grants.sql `$maint$` | aia_maint 对 app.* 拿的是**表级** SELECT/UPDATE/DELETE，所以：<br>• 能读 `user_data_licences.ciphertext`（实测 `has_column_privilege` = t；密文仍是封装过的，需要 ingest 私钥才能解开）；<br>• 能读 `users.password_hash`；<br>• 能 UPDATE `users.role`。<br>裁定 ① 写的是“表与列最小”。review-8fd9502 当时写的是“与 api 相同即可”，所以定为 m。 | 至少对 user_data_licences 照 aia_api 的做法改成列级授权（去掉 ciphertext）；UPDATE 只授给 CLI 实际要改的列（users.status，以及匿名化用到的列） | 运维（后端提供列清单） |
| m4 | grants.sql `$maint_members$` | 撤销是按“aia_maint 的所有成员”整体做的，前提是 owner 是超级用户。PG16 下如果 owner 是非超级用户的 CREATEROLE 角色，建角色时会自动拿到 ADMIN membership：撤销可能失败，或者让末尾自检报错。compose 和 CI 下 owner 都是超级用户，不受影响。 | 在 runbook 写明前提；或者在脚本开头断言 `current_user` 是 rolsuper | 运维 |
| m5 | deploy/docker/secret-env.sh | 拼出来的 DSN 临时文件（600）在进程退出后不删除。maint-cli 用 `run --rm` 跑，没有问题；但如果有人不加 `--rm`，这个文件会一直留在已停止的容器里。 | 改成 CLI 进程结束后删除（不 exec，用 trap 收尾），或者写到 tmpfs，并在 runbook 强调必须加 `--rm` | 运维 |
| m6 | verify-roles.sh | 在生产库上执行时会临时写入 t_o11_ 探针用户（结尾有断言确认无残留）；pending 表的 SIUD 检查是靠真的执行语句来判断，而不是 `has_table_privilege` | 可以接受。建议在 runbook 注明“会写入并删除探针行” | 运维 |
| m7 | check_secret_boundary.py | 没有检查导入卷只挂给 api 和 maint-cli（T-O11 的目标之一），以后有人给 worker 加回挂载时 CI 不会报 | 增加规则：`imports` 卷只允许挂在 api 和 maint-cli 上 | 运维 |

### 其余核对（没有问题）
- **APP_MASTER_KEY 是否泄漏**：
  - `.env.example` 已删掉赋值行；
  - 没有服务用 env_file，compose 里没有任何服务的 environment 含 APP_MASTER_KEY（CI 规则 7 覆盖）；
  - Dockerfile 没有 COPY 或 ENV 密钥，镜像层里没有；
  - secret-env.sh 不开 `set -x`、不打印值；环境变量里已有 APP_MASTER_KEY 时直接拒绝启动，文件为空时也拒绝；
  - keygen 脚本不打印、不覆盖、拒绝写进仓库目录；
  - .gitignore 已覆盖 app_master_key*、db_password_*、*.dsn。
- **maint-cli**：
  - 放在 profile maint 下，`up` 不会启动；
  - 没有 DATABASE_URL，没有 app_master_key；
  - 只挂 db_password_aia_maint、imports 卷、只读 config、secret-env.sh。
- **imports 卷**：只挂给 api 和 maint-cli，挂载点跟随 IMPORT_STORAGE_PATH；worker 不再挂。grep 确认后端只有 importing/storage.py 用到这个卷；镜像内目录权限 700。
- **db-role-passwords.sh 和 apply-roles.sh**：都用 600 文件、十六进制口令、不打印；新生成的 maint 口令属主改为 10001。

## 测试结果

| 项目 | 结果 |
|---|---|
| 新库 `alembic upgrade head`（0001→0015） | ✓ |
| apply-roles.sh 连续执行 2 次 | ✓ rc=0。两次前后 pg_class ACL、列 ACL、membership 快照完全一致（358 行）。default ACL 第二次没有做 diff，但 verify 结果相同 |
| verify-roles.sh 执行 2 次 | ✓ 每次 33 项 OK，没有 FAIL（运维更正后的数字 33 属实） |
| 对抗：预先造出 membership 和权限（`aia_api ∈ aia_maint`、`aia_maint ∈ aia_api WITH ADMIN`、`aia_ingest ∈ aia_maint`，其中一条由第三方 grantor 授出；另外给 aia_api 授 pending 表 ALL 和 ciphertext 列 SELECT），然后执行 apply | ✓ 所有 membership 都被清掉（包括第三方 grantor 授出的那条）；pending 表的 ACL 恢复为只有 aia、aia_maint；ciphertext 列 SELECT 被收回；verify 33/33 |
| 反证：07a4e2b 版 grants.sql 在已有 membership 时执行 | ✗ 按预期被 `$grants$` 自检中止（这正是偏差的理由） |
| CLI dry-run 用 aia_api DSN | ✓ 被拒绝 |
| CLI 不用 maint DSN 执行 `--execute` | ✓ 被拒绝 |
| CLI 以 aia_maint 执行 `--execute`（造一个用户：profile、account、batch、file、login_attempt、notification、licence、licence 事件，外加磁盘上的导入文件） | ✓ 9 类行全部处理：licence 事件匿名化，其余删除；写入审计 `admin.user_data_deleted`；磁盘文件已删 |
| 文件删不掉的场景（目录设为 555） | ✓ 数据库已提交，2 条进入 pending（INSERT … ON CONFLICT），退出码 3。恢复目录权限后，下一次执行时 `retry_pending` 清空了队列 |
| 结论：aia_maint 的权限够 `--execute` 全流程用 | ✓（evaluation schema 没有表引用 app.users；CLI 动态发现的范围只在 app/ops/market） |
| scripts/ci/tests（不带 gitleaks） | 218 passed / 55 skipped，共 273 项，与运维报告一致 |
| scripts/ci/tests（带 /tmp/gitleaks-bin 8.21.2） | 268 passed / 5 failed。7a3e9cb 基线同样是 5 个失败，是本地 gitleaks 版本或环境造成的，与 T-O11 无关 |
| test_secret_boundary.py | 41 passed |
| check_secret_boundary.py | OK |
| secret_scan.py tree（导出目录） | 524 个文件版本，阻断 0 |
| secret_scan.py range 7a3e9cb..47c4b9c / 0cb78ad..a8e055b | 22 / 380 个文件版本，阻断 0 |
| gitleaks git 0cb78ad..a8e055b（仓库配置） | no leaks found |

## 推送顺序

### 各评审报告结论

| 报告 | 结论 |
|---|---|
| review-T-B02y | 492898b 有条件通过（M1 已由 c55a42e 修掉）；a6c1437 通过 |
| review-6c50108 | 通过（d1fccf6 是 6c50108 的 amend，结论沿用） |
| review-457a211 | 通过 |
| review-116cb7e | 有条件通过 |
| review-8249d6e | 通过 |
| review-c55a42e | 通过 |
| review-7afbc06 | 通过 |
| review-45589c2 | 不通过（B1、B2），已由 8fd9502 修复 |
| review-717bce0 | 通过 |
| review-85e9b70 | 通过 |
| review-be607b3 | 有条件通过 |
| review-8fd9502 | 有条件通过（运维前置由本次 T-O11 补齐；m1–m3 中 m1、m2 已由 a8e055b 处理，a8e055b 尚未评审） |
| review-9547181 | 通过 |
| review-b34260f | 通过 |
| review-53468a5 | 通过 |
| review-d26e1d3 | 通过 |
| review-f72b8c7 | 通过 |
| review-b23401a | 有条件通过（m 级，不阻断） |
| review-bbf58a0 | 有条件通过（3 个 M，不阻断） |
| review-c9e1e73 | 有条件通过（3 个 M） |
| review-T-O11（本文） | 07a4e2b 有条件通过；47c4b9c 通过 |
| review-527b65e、review-39c6d80 | 跳过（已被前面的评审覆盖） |
| review-b23401a-fixes-frontend | 这是前端自己的返修报告，**不是评审**；d0c7ccb 仍待评审 |

### origin/main（0cb78ad）之后的 41 个提交，从旧到新

| # | 提交 | 状态 |
|---|---|---|
| 1 | 492898b | 有条件通过（条件已由 c55a42e 满足） |
| 2 | a6c1437 | 通过 |
| 3 | 6ef79c4 | docs |
| 4 | f7ddc8c | docs |
| 5 | d1fccf6 | 通过 |
| 6 | 457a211 | 通过 |
| 7 | 116cb7e | 有条件通过 |
| 8 | 8249d6e | 通过 |
| 9 | 307132b | docs |
| 10 | c55a42e | 通过 |
| 11 | 7afbc06 | 通过 |
| 12 | 4caedc0 | docs |
| 13 | 45589c2 | 不通过 → 由 8fd9502 修复；**必须和 8fd9502 一起推** |
| 14 | 717bce0 | 通过 |
| 15 | 67d123a | docs |
| 16 | 8a760d1 | docs |
| 17 | 85e9b70 | 通过 |
| 18 | be607b3 | 有条件通过 |
| 19 | 8fd9502 | 有条件通过 |
| 20 | 9547181 | 通过 |
| 21 | b34260f | 通过 |
| 22 | 53468a5 | 通过 |
| 23 | d26e1d3 | 通过 |
| 24 | f72b8c7 | 通过 |
| 25 | 687159f | docs |
| 26 | b23401a | 有条件通过 |
| 27 | 439746e | docs |
| 28 | 483fe2c | docs |
| 29 | **bbf58a0** | 有条件通过 ← **当前可安全推送的最远位置** |
| 30 | d0c7ccb | **未评审** |
| 31 | c9e1e73 | 有条件通过 |
| 32 | 7a3e9cb | **未评审** |
| 33 | 07a4e2b | 有条件通过（本文） |
| 34 | 0f8129b | **未评审**（另有已知缺口：/meta/enums 少 3 个 v0.2.9 枚举） |
| 35 | 4532478 | docs |
| 36 | 47c4b9c | 通过（本文） |
| 37 | 5c282da | **未评审** |
| 38 | db486aa | docs |
| 39 | a8e055b | **未评审**（含迁移 0015） |
| 40 | 07b8d74 | **未评审**（评审期间新增） |
| 41 | 0e31218 | **未评审**（评审期间新增） |

### 推送点

- **现在可以推到 bbf58a0**（只推前缀，例如 `git push origin bbf58a0:main`）。这一段里没有未评审的代码提交；45589c2 和 8fd9502 都在里面，45589c2 不再阻断。
- **卡点：**
  - **d0c7ccb**（前端 b23401a 返修，未评审，需重点看 N8 和 m2 的续加载上限）：评审通过后，推送点可以推进到 c9e1e73。
  - **7a3e9cb**（T-A10 前端同步，未评审）：评审通过后，推送点可以推进到 07a4e2b。但 07a4e2b 不应单独推，应等 47c4b9c。
  - **0f8129b** 夹在 07a4e2b 和 47c4b9c 之间：它不评审通过，T-O11 就推不上去。另外它的枚举缺口需要后端补，或者明确裁定放到后续提交。
  - **5c282da、a8e055b、07b8d74、0e31218**：都在 47c4b9c 之后，未评审。a8e055b 带迁移 0015。
- **部署提醒**：推到 bbf58a0 只是推代码。bbf58a0 包含迁移 0011–0014，但不包含 T-O11 的 grants。在 T-O11 推送并部署之前，任何环境都**不应**升级到 0011 及以上去跑生产：
  - aia_api、aia_ingest 仍能读写 pending 队列；
  - 删除用户数据 CLI 无法执行 `--execute`。

### 推送前（以及上线前）要在每个目标库上跑的检查

```sql
-- 1. 0009 回填前提（在 0008 上统计；或者确认 c55a42e 版 0009 已执行）
SELECT status, count(*) FROM app.strategy_instances WHERE status IN ('paused','archived') GROUP BY 1;
SELECT count(*) FROM market.securities;           -- 非空时，守卫触发器会拒绝未知代码
-- 2. 是否有环境跑过旧版 0009（c55a42e 之前的版本）
SELECT version_num FROM alembic_version;          -- 版本 ≥ 0009 且来自旧代码时，要单独回填
SELECT count(*) FROM app.strategy_instances WHERE (status='paused' AND paused_by IS NULL) OR (status='archived' AND archived_at IS NULL);  -- 必须为 0
-- 3. 0010（证书暂停与 holds）
SELECT count(*) FROM app.user_data_licences WHERE status='paused_by_admin' AND deleted_at IS NULL;
-- 另外统计：只剩已删除 paused 行的用户（review-116cb7e m5）
-- 4. 迁移后
--    bash deploy/db/roles/apply-roles.sh   # 连续执行两次
--    bash deploy/db/roles/verify-roles.sh  # 应为 33 项 OK
SELECT pg_has_role('aia_api','aia_maint','MEMBER'), pg_has_role('aia_ingest','aia_maint','MEMBER');   -- 都应为 f
SELECT has_table_privilege('aia_api','ops.pending_file_purges','SELECT');                             -- 应为 f
```
5. 生产环境不要设置 `DATA_LICENCE_SETTINGS_ENABLED=true`（不设置或设为 false）。
6. （本次新增）已有部署升级前，先把 `.env` 里原有的 APP_MASTER_KEY 迁到 `$AIA_SECRETS_DIR/app_master_key`（600，属主 10001），再跑 compose.sh（见 M1）。

## 谁要做什么

| 谁 | 做什么 |
|---|---|
| 运维 | 1. 修 M1（compose.sh 遇到旧主密钥时拒绝自动生成，或迁移旧值）。<br>2. m3–m7 可以放到后续提交。<br>3. nginx 502（`up --build` 后 nginx 没有重建）另立任务。<br>4. 按上面的清单跑库检查。<br>5. 推送前缀：bbf58a0。 |
| 后端 | 1. m1：CLI 去掉环境变量回落。<br>2. m2：dry-run 拒绝 owner DSN。<br>3. 给运维提供 m3 的列清单。<br>4. 0f8129b 补齐 /meta/enums 缺的 3 个枚举。<br>5. 按裁定处理 M2。 |
| 架构师 | 1. 裁定 M2（主密钥按服务校验，还是给所有服务挂主密钥）。<br>2. 评审 d0c7ccb、7a3e9cb、0f8129b、5c282da、a8e055b、07b8d74、0e31218。<br>3. 每评完一批，就把推送点往后推进。 |
| 当事人（不明） | 确认主仓库 stash<at>{0} 去向（T-O11.md 第 90 行）。 |
