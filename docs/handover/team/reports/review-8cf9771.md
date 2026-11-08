# 复审：8cf9771（75c233b 的 B1/m1/m2/n1/n2 修复）+ c340ce1（runbook 主密钥迁移/恢复）

评审人：项目架构师。方式：在 /tmp/arv-8cf 干净导出（git archive 8cf9771 + git init）里只读复审。
- gitleaks 用 8.30.1；
- 没有起容器：docker 一律用桩脚本代替，只运行了本机 `docker compose v5.6.1 config` 做解析对照（不起容器）；
- 实验用的 HOME 和密钥目录都放在 /tmp 下，用完已删除；
- 所有密钥都是运行时随机生成的假值。

## 结论
- **8cf9771 和 c340ce1 可以推送。**
  - `scripts/ci/tests` **441 passed**，其中包含与真实 compose 逐例对照的测试；`check_secret_boundary` 通过。
  - B1 已修好。
- **可以无人值守地就地升级部署。**
  - .env 的各种写法，结果要么与 compose 读到的值一致，要么拒绝；没有发现会悄悄迁移错误值的情况。
  - 预期现象：如果之前在 1cf643e 或 75c233b 上迁移过、而 .env 那一行带行尾注释，④ 现在会发现文件和 .env 不一致，于是拒绝启动。这是正确的行为，按 runbook 由人确认即可。
- **迁移到新主机：先不要照 runbook 第 2 步执行。** runbook 写的是 `compose.sh up -d --wait`，这会把 ingest 一起启动，违反 plan §1.3 的“先不启动 ingest”，新旧两台主机会同时用同一张证书外呼（违反 2.1A），见 M1。修好之前，迁移按 plan 的顺序人工执行。

## 1. B1：.env 解析（✅ 已修）
用 39 种写法逐一对照：每种写法分别跑 ensure 的迁移路径，同时用 `docker compose config` 读出 compose 实际得到的值，再比较两者。

| 写法 | ensure 的结果 | compose 读到的值 | 判定 |
|---|---|---|---|
| `KEY=<K>  # 注释` | 迁移 K | K | 一致 |
| `KEY="<K>" # c` | 迁移 K | K | 一致 |
| `KEY='<K>'`、`'<K>' # c`、`"<K>"`、`"<K>"  ` | K | K | 一致 |
| `KEY=<K> #x`、`<K>  #`、`<K> ##` | K | K | 一致 |
| `KEY=<K>#tail`、`'<K>#in'`、`"a#<K>"`、`KEY= #<K>` | 值里带 #，迁移的就是带 # 的值 | 同左 | 一致（compose 只把“空格+#”当注释） |
| `export KEY=<K>`、`KEY = <K>`、行首有空格、行尾有 `\r`、同名多行取最后一行、被注释掉的同名行 | K | K | 一致 |
| `KEY=<K>\\x`、`"<K>'"`、`<K>'q'` | 原样迁移 | 原样 | 一致 |
| `KEY='<K>$X'` | 迁移 K$X | config 输出里显示为 K$$X | 一致（`$$` 是 config 输出时的转义，容器里实际是 K$X） |
| `KEY=<K>\t#tab`、`"<K> #in"`、`KEY=  # 注释`、`<K> trailing` | **拒绝**（值里有空白） | 带空白或 # 的值 | 拒绝，安全 |
| `"<K>"x`、`'<K>'"x"`、`'<K>`（引号不配对）、`"<K>\n"`（转义） | **拒绝** | 有差异或 compose 自己报错 | 拒绝，安全 |
| `<K>$X`、`"<K>$X"`（会被插值）、`KEY: <K>` | **拒绝** | 插值后的值 | 拒绝，安全 |
| 最后一行为空值或 changeme | 视为没有旧值，接着走 ③ | 空值 / changeme | 安全 |

**所有输出里都没有出现密钥值。**

**遗留问题 m1：占位判断用的是解析前的整行。** 行尾注释里只要有 `<` 或 `>`（例如 `KEY=<K>  # see <docs>`、`# a -> b`），整行就被当成占位值：
- **④ 被跳过**：实测密钥文件为 K1、.env 为 K2 并带这样的注释时，rc=0，**没有拒绝**（检查模式下也一样）；
- ② 的情况会落到 ③：库里有数据时拒绝，但报错提示“请从备份恢复主密钥”，会误导操作人。

<redacted:sensitive-value-or-command>
修法：先解析，再对解析出的值做 is_real 判断；同时补测试（注释里带 `<` 和 `>` 的情况）。

## 2. m1：入口包装防绕过（✅ 主体已修，还有缺口）
CI 实验的写法是：在副本里加一个 `docker-compose.zz.yml` override。

| 写法 | 结果 |
|---|---|
| environment 设 `AIA_SECRET_ENV_DIR`（映射写法 / 列表写法；ingest / api） | ❌ 拦住 |
| 卷挂 `${AIA_SECRETS_DIR}`、`$AIA_SECRETS_DIR`、长格式 bind、`~/.config/aia/secrets` | ❌ 拦住 |
| `!reset` / `!override`、YAML 语法错、顶层不是映射 | ❌ 给出明确的 `::error`，**不再崩溃** |
| cooldown-purge 挂主密钥、ingest 的 env 里有 APP_MASTER_KEY、api 去掉 REQUIRE、用 extends 派生出未登记的服务 | ❌ 拦住 |
| **新定义一个 secret（如 `k2`），file 指向 `${AIA_SECRETS_DIR}/app_master_key`，挂给 ingest** | **通过** |
| **用同样的别名方式把 `data_licence_seal_private_keys` 挂给 api** | **通过**（这是 T-O09 以来就有的缺口：私钥和主密钥可以同处一个容器） |
| **override 里把 `app_master_key` 的 file 改成别的路径** | **通过**（等于悄悄换了主密钥的来源） |
| **用 `configs:` 的 file 指向主密钥文件** | **通过** |
| **命名卷用 `driver_opts.device: ${AIA_SECRETS_DIR}` 做 bind** | **通过** |
| `include:` 外部文件 | 通过 |
| 挂载上级目录（`~/.config/aia`、`${HOME}`、`/`），或用其他变量间接指向密钥目录 | 通过（这类只能靠代码评审，记为 n） |

以上都需要故意改配置。**m2（CI）**：
- 顶层 secrets 和 configs 的 `file`，如果文件名是 `app_master_key` 或 `data_licence_seal_*`，只允许用规定的 secret 名；
- `app_master_key` 和证书相关 secret 只能在基础 compose 里定义，override 不得重定义；
- configs 和 `volumes.*.driver_opts` 里不得引用 AIA_SECRETS_DIR；
- 禁止 `include:`。

**运维的偏差 B（拦截规则对所有服务生效）：可以接受。**
- api 和 worker 是经 `secrets:` 合法拿到主密钥的，`*secret-env-mount` 卷（`../docker/secret-env.sh`）不含被拦的关键字；
- 现有两个 compose 文件里的所有服务（含 cooldown-purge）CI 都通过；
- 没有任何服务需要设置 AIA_SECRET_ENV_DIR（只在单元测试里设，不在 compose 里）。

## 3. m2：哪些子命令强制检查（✅）
- 抽出 `compose_subcmd` 单独测了 24 种参数组合：全局选项后面跟的值都能正确跳过（`-f`、`-p`、`--profile`、`--env-file`、`--ansi`、`--parallel`、`--project-directory`、`--`、`-pfoo`、`--profile=x`）。这份列表与 compose v5.6.1 的 `--help` 核对过，凡是要带值的全局选项都已列入。
- 用 docker 桩脚本端到端跑 `compose.sh`，场景是密钥文件与 .env 不一致：
  - `down` / `ps` / `logs` / `stop`：rc=0，打出告警后继续执行 docker compose，**不会被挡住**；
  - `up -d`：rc=3，docker compose 没有被调用。
- 检查模式不迁移、不生成，也不为 ③ 起容器。
- **运维的偏差 A（watch、scale 也强制）：可以接受。** 但声称的“认不出的子命令也强制”只在取不到子命令（参数为空，或 `-f` 后面没有值）时成立。像 `foo` 这样非空但不认识的名字，走的是检查模式。目前 compose 会直接拒绝未知子命令，所以没有风险。建议（n1）把逻辑反过来：列出只读子命令的白名单（down ps logs stop kill rm exec config images top port events pause unpause ls version cp wait stats attach），白名单以外一律强制。这样才真正符合说明，将来 compose 新增会起容器的子命令也能被覆盖。

## 4. n1/n2：③ 查库（✅）
- 加查 `app.llm_providers.api_key_ciphertext IS NOT NULL`：表或列不存在时算 0（用 information_schema 判断），表名写死。
- 只读两道保护：`PGOPTIONS=-c default_transaction_read_only=on` 加上 `BEGIN READ ONLY … COMMIT`；`-q` 会压掉 BEGIN/COMMIT 的输出，不影响解析。
- 按要求没有起容器，所以 SQL 没有在真实 PG 上执行过。结构与 75c233b 相同（CASE 加上 volatile 的 query_to_xml，不会被提前求值）。建议（n2）运维在 CI 的 PG 服务容器或临时容器里补一个真实 PG 的用例。
- runbook 的 ③ 那一行还没写上 llm_providers（n3）。

## 5. c340ce1：runbook（✅ 两点都写了；⚠️ 与 plan 有一处不一致）
- ✅ 备份：主密钥单独离线保存，按 600 放到离线介质或密码管理器，不和 dump 放在一起，dump 目录里不放任何密钥文件；证书私钥同理。
- ✅ 迁移和灾后恢复：**先**把原主密钥拷到同一路径（600、属主 10001），证书私钥和公钥也先拷，**然后**才 up 和 restore；写明了顺序反过来的后果、恢复后怎么核对、误生成了新密钥怎么处理。
- **M1：第 2 步 `compose.sh up -d --wait` 会把 ingest 一起启动。** plan §1.3（225d2ef）的顺序是“新主机 up（**先不启动 ingest**）→ pg_restore → 改 DNS → 停本地 ingest → 等 ≥60 秒 → 启服务器 ingest → 核对出口 IP”。照 runbook 做，新旧两台主机会同时用同一张证书外呼，违反 2.1A。
  - **以 plan 为准，由 runbook 改正**，所以不改 plan：第 2 步改成不启动 ingest（例如 `up -d --wait --scale ingest=0`，或列出除 ingest 外的服务），后面的步骤指向 plan 的 ingest 切换顺序和 ingest-failover runbook。
  - 只是灾后恢复（原主机已经不在了）的话，可以注明直接启动 ingest。
- n4：runbook 没写恢复原始文件卷（plan 里说的“原始文件卷打包”）。导入文件的密文依赖主密钥，应写明它和 dump 一起恢复、在拷主密钥之后。
- n5：第 3 步要求“sha256 与原主机记录一致”，但备份那一节没写要记录主密钥的 sha256。

## 6. 泄密路径
| 路径 | 结果 |
|---|---|
| 普通输出 / 拒绝提示 | ✅ 39 种写法 + ④ + compose.sh 端到端，输出里都没有密钥值；拒绝提示只写原因 |
| 进程参数 | ✅ 密钥值只经变量、管道和 printf 内建传递；`sudo -n cat` 的参数只有路径；`docker exec -e` 传的只是 PGOPTIONS |
| 临时文件 | ✅ umask 077，放在密钥目录内（mktemp），600，用 `mv -n` 落盘；EXIT trap 会清理；并发创建时拒绝、不覆盖。被 SIGKILL 时可能残留一个 600 的临时文件，仍在密钥目录里，可以接受 |
| `bash -x compose.sh` | ✅ 子进程不继承 xtrace，没有泄露 |
| **继承了 xtrace（`SHELLOPTS=xtrace` 被导出，或直接 `bash -x app-master-key-ensure.sh` 排错）** | **泄露：stderr 里 12～14 行 `raw='<K>  # c'`、`file_val=…`**（m3） |

m3 修法：ensure、keygen 和 secret-env.sh 开头加 `{ set +x; } 2>/dev/null`。compose.sh 读 db 口令那一段同理（早就存在的问题，一并修）。runbook 里写明排错时不要用 -x。

## 分级汇总
| 级别 | 问题 | 阻塞推送 | 阻塞就地升级 | 阻塞新主机迁移 |
|---|---|---|---|---|
| **M1** | runbook 迁移第 2 步会启动 ingest，与 plan“先不启动 ingest”冲突（违反 2.1A） | 否 | 否 | **是**（修好前按 plan 人工执行） |
| m1 | 占位判断用的是解析前的整行，注释里带 `<`/`>` 时 ④ 被跳过，② 的报错误导 | 否 | 否 | 否 |
| m2 | CI 没拦：secret/config 别名指向主密钥或证书私钥文件、override 重定义 app_master_key 的 file、driver_opts.device、include | 否 | 否 | 否 |
| m3 | 继承 xtrace 时 ensure 会打印密钥值 | 否 | 否 | 否 |
| n1 | 非空但不认识的子命令走检查模式（与说明不符），建议改成只读子命令白名单 | 否 | 否 | 否 |
| n2 | ③ 的 SQL 没在真实 PG 上测过 | 否 | 否 | 否 |
| n3–n5 | runbook：③ 那行补 llm_providers；补恢复导入卷；备份时记录主密钥 sha256 | 否 | 否 | 否 |

## 谁做什么
- **运维**：
  1. 推送 c340ce1 和 8cf9771。
  2. 先修 M1：runbook 迁移步骤改成不启动 ingest，并接上 plan 的 ingest 切换顺序。
  3. 修 m1：先解析再做占位判断，补测试。
  4. 修 m3：`set +x`。
  5. 修 m2：补 CI 规则和测试。
  6. 处理 n1–n5。
- **后端**：ingest 启动时发现主密钥就拒绝（plan 要求，之前一直遗留）。
- **架构师**：复审 M1 和 m1–m3 的修复。plan 不改：runbook 与 plan 的冲突以 plan 为准，由 runbook 改正。
