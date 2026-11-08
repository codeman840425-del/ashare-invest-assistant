# 评审：1cf643e fix(deploy): M1 不悄悄生成新 APP_MASTER_KEY

评审人：项目架构师；方式：/tmp/arv-1cf643e 干净导出（git archive + git init），只读。对照 docs/plan.md §1.3“升级约束”①–⑤（e56462c）。

## 结论
**有条件通过，可以推送**（与现状 07a4e2b 的“缺文件就生成”相比是净改进，不会扩大风险）。但 **M1 不满足约束④**，修好之前**不得在已有部署上运行升级**。运维工作区里已有修 ④ 的未提交改动（见下文），提交后需要复审。

## 逐条核对
| 约束 | 结果 | 依据 |
|---|---|---|
| ① 不自动生成；只在全新空库时生成 | ✅ | compose.sh 不再调用 keygen（CI 规则 8 检查）。生成前必须同时满足：docker 可用；导入卷不存在或为空；pgdata 不存在或没有业务表 |
| ② 旧 .env 有值 → 迁移进 600 文件、不打印 | ✅ | umask 077，在密钥目录内 mktemp，printf 是内建命令（值不进 argv），chmod 600，chown 10001，`mv -n`。不打印值，提示由人决定是否删除 .env 那一行。也接受调用方环境变量（是对约束的合理扩展）；两处值不一致时拒绝 |
| ③ 都没有、库有数据 → 拒绝 | ✅（更严） | 有任何非系统表（含 alembic_version）就拒绝；另外导入卷有文件也拒绝 |
| ③ 连不上库 → 拒绝 | ✅ | 访问不了 docker、卷在但没有运行中的 postgres、查询失败、结果无法解析，都退出 3（fail-closed） |
| ④ 两边都有且不一致 → 拒绝 | ❌ **M1** | 见下文 |
| ⑤ 不轮换 | ✅ | 从不覆盖已有文件 |
| AIA_REQUIRE_APP_MASTER_KEY 只给 api/worker | ✅ | 用 yaml 解析全部服务：只有 api、worker 是 "1"。secret-env.sh 缺 secret 时退出 2，不回落到临时密钥 |
| CI 规则 8 | ✅ 合理 | 检查 compose.sh 不直接调用 keygen、调用了 ensure，基础 compose 里 api/worker 的 REQUIRE 为 "1"，任何 override 都不得改掉它 |
| 泄露路径 | ✅ | 没有 set -x；值不进进程参数（测试断言 docker 调用记录里没有密钥值）；临时文件 600、在密钥目录内、EXIT trap 清理；输出只有路径和属主。secret-env.sh 把值导出进容器进程环境，这是设计（docker inspect 看不到） |

## 问题
- **M1（违反约束④）**：
  - compose.sh 只在文件缺失时调用 ensure；ensure 第 1 步“文件已存在 → exit 0”，不和 .env/环境里的旧值比对。
  - 测试 `test_existing_key_used_untouched` 甚至断言“.env 里是另一把也不影响”。
  - 这正是最危险的场景：已运行过 07a4e2b 版 compose.sh 的主机，已经悄悄生成了新文件，而 .env 里还是线上在用的旧 key。1cf643e 会永远接受这把新 key。
  - 修法：
    - compose.sh 每次都调用 ensure。
    - 文件存在且有非占位旧值时逐字节比对（读不到文件就 `sudo -n cat`，仍不行则拒绝）。不一致 → 退出 3；一致 → 提示删除 .env 那一行。
    - 测试改为断言“不一致即拒绝”。
  - **进展**：运维工作区里已有未提交的改动正是这样做的（ensure 头注释写明按 ①–⑤，文件存在时也做 ④ 比对）。我没有碰它，提交后复审。
- **M2（迁移/恢复流程的洞，不是本提交引入的）**：
  - plan §1.3 的迁移流程是“新主机 `docker compose up` → `pg_restore`”。新主机 up 时库是空的，ensure 会合法地生成一把新 key，restore 之后旧数据的 HMAC 和加密文件全部失效。runbook database.md 的恢复章节没有要求先带上 app_master_key。
  - 建议：
    - runbook（迁移、恢复）第一步写明“先把原主机 `$AIA_SECRETS_DIR/app_master_key` 拷到新主机（600、属主 10001），再 up”，备份也要单独离线保存主密钥。
    - db-restore.sh 恢复含 app.users 行的 dump 前，提示核对主密钥来源。
  - plan 迁移流程句我这次没改（不在本次授权的两处改动内），需要时由架构师下一次 docs 提交补上。
- m1：`.env` 解析不处理行尾注释（`KEY=abc  # 注释`）。compose 会把未加引号值里的 ` #…` 当注释，而本脚本会把注释一起迁移进去，迁移进去的值就是另一把 key。建议对未加引号的值去掉 `[[:space:]]#.*`，或者遇到 `#` 直接拒绝并让人确认。
- n1：已有文件不检查长度是否 ≥32（后端会拒绝启动，可以接受）。

## 测试
- 用 CI 同版本 gitleaks 8.30.1：`scripts/ci/tests` **326 passed**，`test_app_master_key_ensure.py` 全部通过。用本机 8.21.2 跑时 test_secret_scan 有 5 个失败，这是 gitleaks 版本差异，与本提交无关。
- `check_secret_boundary.py --repo .`：OK。
