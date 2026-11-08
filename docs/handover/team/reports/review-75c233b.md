# 复审：75c233b T-O11 M2（APP_MASTER_KEY 按服务分配 + 升级约束对齐 plan e56462c，含 1cf643e M1 修复）

评审人：项目架构师。方式：/tmp/arv-75c233b 干净导出（git archive + git init），只读。另在副本 /tmp/arv-byp 里放了 override 文件，试 CI 能否被绕过。gitleaks 用 CI 同版本 8.30.1。

## 结论
- **可以推送。** CI 全绿，相比 1cf643e 是净改进：④ 已修，M2 白名单和 ingest 拒绝都已落地。
- **升级部署：还不能无人值守进行。**
  - **B1 未修**：旧 .env 有行尾注释或“引号 + 注释”时，会把错误的值迁移进密钥文件，等于悄悄换了主密钥。
  - 运维修好 B1 之前，就地升级只能这样做：先由人确认 .env 里 `APP_MASTER_KEY` 那一行是纯值（不加引号或只用单引号，没有 `#`）。或者手工把原值写进密钥文件（600、属主 10001）再 up。
  - 已有密钥文件的主机（如 aia-t01）不受 B1 影响：解析出错只会导致拒绝启动，是安全的。
- **迁移或恢复到新主机：在 M1（runbook）补齐之前，必须人工先把原主机的 app_master_key 拷过去再 up。**

## 逐条核对
### 1. 升级约束①–⑤
| 约束 | 结果 |
|---|---|
| ① 只在全新部署时生成 | ✅ 文件不存在、旧来源没有、库为空（数据卷不存在，或那 4 张表都不存在或都为空）、导入卷为空，同时满足才生成 |
| ② 迁移 | ✅ 流程正确：umask 077、在密钥目录内 mktemp、printf 内建、600、chown、`mv -n`，提示删 .env 那一行。**但解析有缺陷，见 B1** |
| ③ 有数据或连不上库就拒绝 | ✅ 见第 6 条 |
| **④ 文件已存在也比对** | ✅ compose.sh **每次**都调用 ensure。文件存在且旧来源有非占位值时：先直接读文件，读不到改用 `sudo -n cat`（经管道传值），还读不到就拒绝；不一致拒绝（退出 3）；一致则提示删 .env 那一行。比较用的是 `[ ]` 内建，值不进 argv；日志里只有路径；分支结束时 unset 变量。新增 3 个测试覆盖“与 .env 不一致”“与环境变量不一致”“一致”三种情况 |
| ⑤ 不轮换 | ✅ 从不替换已有文件 |

### 2. 1cf643e 的 m1（行尾注释和引号）：**未修，升级为 B1**
解析代码与 1cf643e 完全相同。用随机假值实测（rc=0，都悄悄迁移成功）：
| .env 行 | 迁移进文件的值 |
|---|---|
| `APP_MASTER_KEY=<K>  # prod key` | **<K>␣␣# prod key（76 字符，错的）** |
| `APP_MASTER_KEY="<K>" # c` | **"<K>" # c（70 字符，错的）** |
| `APP_MASTER_KEY='<K>'` | <K>（正确） |

旧版 compose 用 docker compose 自己的 .env 规则插值，线上实际用的是去掉注释和引号后的 <K>。所以迁移结果与线上不同，等于悄悄换了主密钥，下次运行时 ④ 还会认定两者“一致”。
修法：
- 按 compose 的 .env 规则解析：不加引号的值，去掉 `[[:space:]]#.*` 以及之后的内容；加引号的值，取到配对的引号为止，忽略其后的注释。
- 或者更保守：值里含 `#`、或引号后还有内容，就直接拒绝并让人确认。
- 补上述两种格式的测试。

### 3. 1cf643e 的 M2（runbook 迁移/恢复）：**未修 → M1**
runbook 只改了“升级旧部署”的步骤。迁移到新主机、恢复（db-restore）章节都没写“先拷 app_master_key（600、属主 10001）再 up”，也没写“备份时主密钥单独离线保存”（证书私钥 runbook 已有离线介质的写法，可以照抄）。
plan §1.3 的迁移流程是“新主机 compose up → pg_restore”：新主机 up 时库是空的，按 ① 会合法地生成新 key，restore 之后旧数据全部失效。
runbook 目前没有迁移章节（plan 指向的 deploy/scripts/migrate.md 是 T-O06，尚未写），所以**和 plan 没有冲突，本次不改 docs**。建议的 plan 改法见文末。

### 4. MASTER_KEY_ALLOC 白名单：✅
- 表里登记了 13 个服务。用 yaml 核对：docker-compose.yml 和 docker-compose.dev.yml 里没有未登记的服务，表里也没有多余的。
- cooldown-purge 已登记为 False（不挂）。
- CI 扫描 `deploy/compose/*.y*ml`。实测在新 override 里加一个未登记的服务 → 失败。

### 5. ingest 的 AIA_FORBID_APP_MASTER_KEY + 入口包装
- 包装逻辑：FORBID=1 时，只要环境里有 APP_MASTER_KEY（哪怕是空值，用 `+x` 判断）或 `$sd/app_master_key` 存在，就退出 2，否则直接 exec。实测三种情况都符合预期。
- 绕过实验（override 文件 + check_secret_boundary）：
| 手法 | CI |
|---|---|
| 覆盖 entrypoint 为 python / `[]` | ❌ 拦住 |
| `entrypoint: !reset null`、`environment: !reset {}` | yaml 不认识 `!reset` 标签，脚本崩溃，rc=1。属于 fail-closed，但报错信息不明确（m1） |
| FORBID 改成 "0" / 改成只列变量名（透传宿主值） | ❌ 拦住 |
| env_file 注入 | ❌ 拦住（规则 2 全局禁止 env_file）；运行时包装也会发现环境变量 |
| secret 换 target 名挂给 ingest | ❌ 拦住 |
| 覆盖 command | 不需要拦：包装会 exec 新 command，检测照常进行 |
| **ingest 设 `AIA_SECRET_ENV_DIR=/nope`** | **通过**：包装只检查那个目录，看不到 /run/secrets |
| **ingest 挂 `${AIA_SECRETS_DIR}:/s:ro` 卷** | **通过**：主密钥文件以普通卷的方式进入容器 |

<redacted:sensitive-value-or-command>
  - CI 禁止任何服务的 environment 设置 AIA_SECRET_ENV_DIR；
  - CI 禁止任何服务的 volumes 引用 AIA_SECRETS_DIR，或指向 ~/.config/aia/secrets；
  - 解析 compose 时识别 `!reset` / `!override`，给出明确报错。
- plan 要求的**后端侧** ingest 启动检查（发现主密钥就拒绝）还没做，属于后端 M2 的工作，不在本提交范围。

### 6. ③ 对“库有数据”的判定，以及连库的角色和权限
- 判定：app.users、invite_codes、user_data_licences、import_files 任一非空，或导入卷里有文件 → 拒绝。表不存在算 0（允许“迁移过但为空”的库生成，与 ① 一致，有测试覆盖）。数据卷在但没有运行中的 postgres、查询失败、结果无法解析、docker 不可用 → 拒绝。
- 与 1cf643e 相比，去掉了“有任何业务表就拒绝”这一条，变宽松了。但依赖主密钥的数据几乎都经外键挂在 users 上：
  - 冷却指纹、证书 HMAC、shareholder_code_hmac、notify target_ciphertext、导入行，都依附于 users；
  - 只有行情数据时生成新 key 也没有损失。
  - **结论：足够保守。**
- 剩余缺口（n1）：
  - `app.llm_providers.api_key_ciphertext` 是系统级的，理论上 users 为空时也可能存在。建议加查 `count(*) WHERE api_key_ciphertext IS NOT NULL`。
  - 只查 `$POSTGRES_DB`：恢复到其他库名、尚未切换时看不到。runbook 可以要求恢复期间先停用 compose.sh up。
- 角色和权限：
  - 用 `docker exec` 进入挂着 pgdata 的 postgres 容器，以 `$POSTGRES_USER`（引导超级用户，也就是属主）经本地 socket 连库，不需要口令，只执行 `SELECT count(*)`（表名写死，没有注入）。
  - 宿主侧需要 docker 权限（docker 组或 `sudo -n docker`），与 compose.sh 本身的要求相同。
  - **不用 aia_api 是对的**：判定要看到所有表的真实行数，不能受授权或 RLS 影响。
  - 建议（n2）：会话强制只读，例如 `PGOPTIONS='-c default_transaction_read_only=on'`，或用 `BEGIN READ ONLY`。

### 其他
- m2：compose.sh 每次调用都跑 ensure，包括 `down` / `ps` / `logs` / `stop`。一旦拒绝（例如 .env 与文件不一致），连 `down.sh` 都会被挡住。建议只在 up / run / create / start / restart 时强制，其余子命令只告警。`--get` 在 ensure 之前退出，keygen / db-role-passwords 不受影响 ✅。
- 测试：`scripts/ci/tests` **361 passed**（gitleaks 8.30.1）；`check_secret_boundary.py`：OK。

## 分级汇总
| 级别 | 问题 | 是否阻塞推送 | 是否阻塞升级部署 |
|---|---|---|---|
| **B1** | .env 解析不处理行尾注释和“引号 + 注释”，会悄悄迁移错误的主密钥（实测复现） | 否 | **是**（修复前只能人工核对 .env 行，或手工写入密钥文件） |
| **M1** | runbook 没写“迁移/恢复先拷主密钥再 up、主密钥离线备份” | 否 | 阻塞迁移/恢复到新主机；不阻塞就地升级 |
| m1 | 包装可被 `AIA_SECRET_ENV_DIR` 覆盖，或挂载密钥目录卷绕过，CI 不拦；`!reset` 让 CI 崩溃 | 否 | 否 |
| m2 | down/ps/logs 也被 ensure 拒绝挡住 | 否 | 否 |
| n1 | ③ 可加查 llm_providers 的密文；只查主库名 | 否 | 否 |
| n2 | ③ 的查询建议强制只读 | 否 | 否 |

## 建议的 plan 改动（本次未提交，因为 runbook 和 plan 没有冲突）
plan §1.3“迁移流程”句，在“新主机 `docker compose up`”之前插入：“把原主机 `$AIA_SECRETS_DIR/app_master_key` 拷到新主机同一路径（600、属主容器用户）——否则新主机空库会按升级约束①生成新主密钥，`pg_restore` 后既有 HMAC 与加密文件全部失效；主密钥随备份单独离线保存（不与 pg_dump 放在一起）”。
