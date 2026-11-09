# T-A67 P3 合入方案（风控和 0028）与 0029 缺源码时的恢复评估

> 架构师，2026-11-09（America/Denver）。接 T-A64（5944ed1）和 T-A65（760c132）。基线是本地 main = origin/main = cee9cc6（P1 已在）。
> 本任务只读：试 apply 只在临时 worktree 里用 `git apply --3way` 做，用完已删除。没有起容器或数据库，没有碰用户电脑，没有调麦蕊。三项搁置都没动：名单额度 1→3、`enforce:false`、`myip.ipip.net`。
> 远端核对（`git ls-remote`）：只有 `main`、`team-b`，以及新出现的 `tb-T-B102g`（a55e680）。**tb-T-B99e 还没有推上来**；tb-T-B102g 的迁移目录也只到 0028，里面没有 0029。

# 一、P3 合入方案（风控和 0028）

## 1. 摘要

8 个拣入提交，加 3 个新增提交。已试 apply：P3 直接叠在 cee9cc6 上就无冲突，**不依赖 P2**，可以在 P2 之前执行。扫描 17 个文件阻断 0，`diff --check` 无输出，`check_contract` 通过，`ruff check .` 通过。

本次新发现 3 处要补，都放进第 4 节的新增提交：
1. **716cda3 新增 1 个 `mypy --strict` 错误**：`app/api/v1/risk_controls.py` 里 `ResetRoute.get_route_handler` 的返回类型是 `Awaitable`，父类要求 `Coroutine`。main 基线 7 个错误，叠加后 8 个。
2. **`selfchecks/test_tb92_repairs.py:58` 写死了 `get_heads() == ["0027"]`**：0028 进来后，真库运行会失败。team-b 一直没改它。
3. **`verify-roles.sh` 的 T-O42 段在列不存在时输出 SKIP**，这违背 T-O33「未迁移即失败，不跳过充通过」的做法。

## 2. 文件到角色的归属表（DeepSeek 机械整理，8/8 与 numstat 复核一致）

| 提交 | +/- | 文件（角色） | 牵头 | 会签 |
|---|---|---|---|---|
| 9e746d9 | 150/0 | api-contract.md、reports/T-A52.md、reviews/T-A52-risk-control-reset-ruling.md（架构师） | 架构师 | 后端知会 |
| 716cda3 | 538/4 | api/v1/risk_controls.py、db/tables/strategy.py、risk/settings.py、suggestions/risk.py、**migrations/versions/0028_tb95_risk_override_active.py**、selfchecks/test_tb95_reset.py（后端）；reports/T-B95.md（架构师） | **后端** | 架构师复核迁移和报告 |
| be6028b | 25/0 | deploy/db/roles/verify-roles.sh（运维）；reports/T-O42.md（架构师） | **运维** | 架构师复核 ACL |
| c869dcf | 454/101 | api/v1/risk_controls.py、db/migration_check.py、strategy/instances/creation.py、migrations/env.py、selfchecks/test_tb95_reset.py（后端）；reports/T-B98.md（架构师） | **后端** | 架构师复核守卫 |
| f20fd83 | 234/31 | db/migration_check.py、migrations/env.py、selfchecks/test_tb95_reset.py（后端）；reports/T-B98b.md（架构师） | **后端** | 架构师复核守卫 |
| 3f30a99 | 13/15 | reports/T-O42.md（架构师） | 架构师 | 无 |
| b44c2f5 | 16/12 | reports/T-O42.md（架构师） | 架构师 | 无 |
| 93ca4d1 | 15/17 | reports/T-O42.md（架构师） | 架构师 | 无 |

## 3. 通用规则（沿用 T-A65 第 1 节）

- 在集成 worktree 的 `integ/teamb-p3` 分支上操作，从 origin/main 新建，各角色依次接力。
- 每个提交都执行 `git cherry-pick -x <hash>`，再执行 `git commit --amend --no-edit --reset-author`。需要补改的提交，先改文件、`git add`，再 amend，保留 -x 行。作者必须是 noreply 身份。
- 每个提交后都跑 `git diff --check HEAD~1 HEAD` 和 secret_scan，阻断必须为 0。冲突就停下来交架构师。
- 改名：P3 里没有 T-A48/T-A49 引用（已核实），不需要改名。
- 脱敏：残留模式扫描只命中 `127.0.0.1:55495`，属于本机回环上的测试专用端口，可以放行。T-O42/T-B95/T-B98 报告里没有用户名、盘符或公网 IP。

## 4. 逐提交执行单

| 序 | 提交 | 执行人 | 操作 | 预计冲突 |
|---|---|---|---|---|
| 1 | 9e746d9 | 架构师 | pick 加 reset-author | `api-contract.md` 是热点文件，T-A52 段新增在 §7.x 风控处，试 apply 无冲突 |
| 2 | 716cda3 | 后端 | pick 加 reset-author | 无。**0028 迁移**：`revision=0028`，`down_revision=0027`，接在 main 的 0027 后面是线性单链；`python -m app.db.migration_check` 输出 `0028 (single mainline head)` |
| 3 | be6028b | 运维 | pick 加 reset-author | 无 |
| 4 | c869dcf | 后端 | pick 加 reset-author | `risk_controls.py`、`migrations/env.py`，叠加在 716cda3 上，无冲突 |
| 5 | f20fd83 | 后端 | pick 加 reset-author | 无 |
| 6 | （新增）| 后端 | `fix(risk): T-A67 typing and 0028 head pins`：① 把 `ResetRoute.get_route_handler` 的返回类型改成 `Callable[[Request], Coroutine[Any, Any, Response]]`，不改行为。② `test_tb92_repairs.py` 不再断言 head 是 0027，改为显式 `upgrade(cfg, "0027")`，并断言 0027 在 mainline 中。这个测试本来就是测 0027 投影的，被测对象不变 | 无 |
| 7 | （新增）| 运维 | `fix(deploy): T-A67 fail T-O42 when 0028 applied but column missing`：库的 `alembic_version` ≥ 0028 而列缺失时输出 FAIL；只有库还在 0027 时才允许输出「未迁移」说明 | 无 |
| 8 | 3f30a99 | 架构师 | pick | 无 |
| 9 | b44c2f5 | 架构师 | pick | 无 |
| 10 | 93ca4d1 | 架构师 | pick | 无 |
| 11 | （新增，**隔离 PG 全部通过之后再做**）| 架构师 | `docs(contract): T-A67 adopt T-A52 and fix 0028 rollback rule`：契约 T-A52 段从 `status: draft` 改为生效；第 4 条「存储」后面追加第 5 节的正确回滚口径，并引用本文件 | 无 |

P2 联动：如果 P3 先于 P2 合入，P2 的 tb94 隔离库要**显式**执行 `alembic upgrade 0027`，不能用 head，因为 tb94 断言 `alembic_version=0027`；tb97/tb100 自己会 upgrade head，不受影响。

## 5. RV-01 回滚口径纠正（按 0028 和守卫源码复核）

**源码事实**
1. 0028 的 upgrade 只做 `add_column(override_active, Boolean, NOT NULL, server_default=true)`；downgrade 只做 `drop_column`。
2. 清除接口（`risk/settings.py::reset`）**只把 `override_active` 置为 false，不改该行原有的 `enabled`/`params`**，同时向不可变的 `risk_control_settings_history` 追加一行 `enabled=NULL, params=NULL`。
3. 读取路径只有 `effective_config`、`entries` 和快照（c869dcf 起改用 `effective_config`）用 `override_active` 过滤。**716cda3 单独存在时，`creation.py::risk_snapshot` 还没有过滤**，要到 c869dcf 才修好。
4. 启动检查（`require_database_mainline`）要求库版本**在代码自己的迁移链里**，而不是等于 head。
5. 降级守卫（f20fd83）在执行任何 DDL 之前：只要存在 `NOT override_active` 行就拒绝降级；离线 SQL 一律拒绝。

**RV-01 错在哪里**
- 「旧代码对该列无感知」只说对了一半。旧代码确实不读这一列，所以会把 false 行连同原有的 enabled/params **重新当作有效覆盖**，继承语义静默反转。
- 「保持 0028、回滚代码」在实际中分两种情况：
  - (i) 回滚到不含 0028 文件的代码：启动检查直接拒绝启动（库是 0028，旧链里没有它），所以不会「无感知地运行」。真正的风险是**迁移时仍在运行、没重启的旧进程**。
  - (ii) 回滚到 716cda3 到 c869dcf 之前的版本：能通过启动检查，但实例快照会读到已清除的覆盖。
- 旧代码的 PUT 还有一个坑：它只更新 enabled/params，**不会把 override_active 置回 true**。新代码会继续把这一行当作「已清除」，用户新设的值被静默忽略。

**正确口径**（写入契约 T-A52 第 4 条，见第 4 节序号 11）
1. **代码回滚的下限是 f20fd83**（包含 0028、全部 `override_active` 过滤和降级守卫）。任何部署到 ≥0028 库的 api、worker、ingest 代码都不得低于这个版本。
2. 如果必须回到 0028 之前的代码，**只能代码和库一起降到 0027**：先停掉 api/worker/ingest，执行 db-backup.sh，用守卫路径执行 `alembic downgrade 0027`，再启动旧代码。前提是 `SELECT count(*) FROM app.risk_control_settings WHERE NOT override_active` 结果为 0，守卫会自动强制这一条。
3. **downgrade 是否保留事实**：false 行为 0 时，删除这一列不丢任何状态。历史表（不可变触发器保护）和 `risk_control.reset` 审计都保留；历史里 `enabled=NULL` 的清除记录已被之后的 PUT 覆盖，状态一致，这一点已复核。false 行大于 0 时守卫拒绝降级，事实保留在 0028。
4. **「物化」不可行，不作为常规手段**：
   - 删掉 false 行：被不可变历史表的外键（`setting_id`）挡住，强删会破坏审计。
   - 把 false 行改写成当前继承值：会把「继承」冻结成用户从未设置过的显式覆盖，之后系统或画像的变化不再传导，审计上也不真实。
   - 如确需物化，要另立「状态保留型降级脚本」，经评审并由**用户本人批准**。
5. **部署顺序**：先停掉 api/worker/ingest，再迁移到 0028，然后启动新代码，**中间不留任何旧进程**。第一次清除操作必须在所有进程都已升级之后才能发生。
6. 用户库已经在 0028 之后（现在是 0029），并且 T-T31 在真库上做过清除复验，**按存在 false 行处理**。所以部署到用户电脑的代码，必须是 ≥f20fd83 的版本。

## 6. 隔离 PG 复验命令清单（运维准备，测试执行并签字）

基本要求：只绑定 127.0.0.1 的临时端口，用 trust 认证，不连用户库，不挂运行栈的卷，测完删除。

```bash
# 运维：起临时库（compose 同款镜像，仅本机端口）
IMG='timescale/timescaledb:2.31.0-pg16@sha256:322ae364eca3321cf2a48f1ef31213b87843413b3cf8feeebf54e999a26bb731'
docker run -d --rm --name aia-p3-pg -p 127.0.0.1:55495:5432 \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=tb95_test "$IMG"
until pg_isready -h 127.0.0.1 -p 55495 -U postgres -q; do sleep 1; done
psql -X -h 127.0.0.1 -p 55495 -U postgres -c 'CREATE DATABASE aia_p3'
PW="$(mktemp -d)"; chmod 700 "$PW"
for r in aia_api aia_ingest aia_maint; do openssl rand -hex 16 > "$PW/db_password_$r"; done
```

**A. 0027→0028→0027→0028 往返**（测试执行，在 `src/backend` 下，库 aia_p3）
```bash
export DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55495/aia_p3
P="psql -X -tA -h 127.0.0.1 -p 55495 -U postgres -d aia_p3"
uv run --frozen alembic upgrade 0027
pg_dump -s -n app -h 127.0.0.1 -p 55495 -U postgres aia_p3 > /tmp/s0027.sql
# 合成数据：1 个虚构用户，加 1 条 user 覆盖行（position_cap，params 为虚构值）
$P -c "INSERT INTO app.users(id,username,password_hash,status,role) VALUES ('00000000-0000-4000-8000-0000000000a1','p3_synth','x','approved','user')"
$P -c "INSERT INTO app.risk_control_settings(scope,user_id,control,enabled,params) VALUES ('user','00000000-0000-4000-8000-0000000000a1','position_cap',true,'{\"single_position_max_pct\":\"25\"}')"
$P -c "SELECT md5(string_agg(t::text,'|' ORDER BY id)) FROM app.risk_control_settings t" > /tmp/d0027.txt
uv run --frozen alembic upgrade 0028
$P -c "SELECT is_nullable, column_default FROM information_schema.columns WHERE table_schema='app' AND table_name='risk_control_settings' AND column_name='override_active'"   # 期望 NO | true
$P -c "SELECT count(*) FROM app.risk_control_settings WHERE NOT override_active"                    # 期望 0
uv run --frozen alembic downgrade 0027                                                               # 期望成功
pg_dump -s -n app -h 127.0.0.1 -p 55495 -U postgres aia_p3 | diff /tmp/s0027.sql -                 # 期望无差异
$P -c "SELECT md5(string_agg(t::text,'|' ORDER BY id)) FROM app.risk_control_settings t" | diff /tmp/d0027.txt -   # 期望无差异
uv run --frozen alembic upgrade 0028
# 负例：制造一条已清除覆盖，降级必须被拒绝，并保持 0028
$P -c "UPDATE app.risk_control_settings SET override_active=false WHERE user_id='00000000-0000-4000-8000-0000000000a1'"
uv run --frozen alembic downgrade 0027; test $? -ne 0                                                # 期望输出 UNSAFE_DOWNGRADE_0028
uv run --frozen alembic downgrade 0028:0027 --sql; test $? -ne 0                                     # 离线也拒绝
uv run --frozen alembic current                                                                      # 期望 0028
$P -c "SELECT count(*) FROM app.risk_control_settings WHERE NOT override_active"                    # 期望 1，事实保留
uv run --frozen alembic heads                                                                        # 期望只有 0028
```

**B. 最小 ACL**（运维执行 apply，测试执行 verify 并签字；库 aia_p3 在 0028）
```bash
cd <repo>
AIA_DB_ROLE_PASSWORD_DIR="$PW" PGHOST=127.0.0.1 PGPORT=55495 PGUSER=postgres PGDATABASE=aia_p3 bash deploy/db/roles/apply-roles.sh
AIA_DB_ROLE_PASSWORD_DIR="$PW" PGHOST=127.0.0.1 PGPORT=55495 PGUSER=postgres PGDATABASE=aia_p3 bash deploy/db/roles/verify-roles.sh | tee /tmp/p3-roles.txt
grep -c '^FAIL' /tmp/p3-roles.txt                    # 期望 0（退出码 0）
grep -c 'SKIP T-O42' /tmp/p3-roles.txt               # 期望 0
grep -c '^OK .*override_active' /tmp/p3-roles.txt    # 期望 4：api 读和写 OK，maint 读和写都 permission denied
```
这一步参照 T-O33 五表的做法：正例和反例都写成 `WHERE false`，不动数据；对象缺失就判失败，不跳过。

**C. 风控用例**（测试执行，库 tb95_test，用例自己完成 0027→0028→0027→0028）
```bash
cd src/backend
TB95_ISOLATED_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55495/tb95_test \
  env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY uv run --frozen pytest -q -rs selfchecks/test_tb95_reset.py
# 期望 22 passed，0 failed，0 skipped（10 个函数，按参数展开共 22 例）
```

**D. 静态检查**（后端执行）
- `uv run --frozen ruff check .`
- `uv run --frozen mypy`：错误集合等于 main 基线，新增 0。
- `uv run --frozen python -m app.db.migration_check`：输出 `0028 (single mainline head)`。

**E. 清理**（运维执行）：`docker rm -f aia-p3-pg; rm -rf "$PW" /tmp/s0027.sql /tmp/d0027.txt /tmp/p3-roles.txt`。不留卷。

## 7. 验收和推送点

**通过**（全部满足）
1. 10 个提交（含 3 个新增）的作者都是 noreply 身份，都带 -x 行（新增的 3 个除外），顺序与第 4 节一致。
2. 每个提交扫描为 0，`diff --check` 无输出。
3. A 段每一步都与期望一致；B 段 FAIL 为 0、SKIP 为 0、override_active 相关 OK 为 4；C 段 22 passed、0 failed、0 skipped；D 段全部满足。
4. `git diff origin/main...HEAD --stat` 只包含第 2 节列出的文件，加上新增提交涉及的 `risk_controls.py`、`test_tb92_repairs.py`、`verify-roles.sh`、`api-contract.md`。**不得**出现 `app/ingest/`、`config/ingest.yaml`、`deploy/compose/`、`0029*`。
5. 序号 11 的契约提交已经完成。

**失败**：任何一条不满足，或者有用例被跳过、为了通过而改测试、出现冲突，都不推送，回到架构师。

**推送点 P3**：测试签字 A/B/C，运维签字 B/E，架构师签字第 5 节和序号 11。之后由编排者 ff-only 到 main，**经用户确认**后由运维执行 `git push origin main`（不 force），再用 `git ls-remote` 核对。

**必须等用户确认的事项**：推送 P3；把含 0028 的代码部署到用户电脑；任何物化脚本或对用户库的降级。

# 二、0029 缺源码时恢复用户电脑 API 的最小路径（只评估）

## 8. 拒启逻辑复核（main 上的 `src/backend/app/db/migration_check.py`）

- api 由 `app/main.py:55` 在启动时调用 `check_startup`，worker 由 `app/workers/runner.py:35` 调用。流程是：`require_single_head`，然后 `require_database_mainline`，然后 engine policy 检查。
- `require_database_mainline` 读取 `public.alembic_version`。只要库版本**不在代码 `script.walk_revisions()` 的集合里**，就抛出 `DATABASE_REVISION_NOT_MAINLINE: <ver>; stop; no automatic stamp/downgrade`。注意它**不要求库版本等于 head**：库落后于代码可以启动，库领先于代码（版本未知）就拒绝。
- `migrations/env.py` 在线模式下执行迁移前也会调用同一个检查（`allow_empty=True`）。所以**用不含 0029 文件的代码，连 `alembic downgrade` 都跑不了**：先被这个检查拒绝，而且 Alembic 本身也找不到 0029 这个版本。
- 推论：用户库在 0029 时，**任何不含 0029 迁移文件的代码都起不来**。热重载发生时，api 重新执行了启动检查，这正是现在拒启的原因。
- 本仓库所有分支和 tb-T-B102g 的代码里，都没有对 `ingest_private` 或 `certificate_bindings` 的引用（已 grep），只有 team-b 的 runbook 里有文字提及。**0029 建的对象，现有代码都不使用**。
- 根据 T-O45 报告（自报，未复核），0029 建了 `ingest_private` schema 加 RLS，只给 aia_ingest；里面有 `mairui_gate_bindings` 和 `mairui_gate_scopes` 两张表，并且**已经写入一条活绑定**。升 0029 之前备份过一份 `deploy/backups/aia-20261109T050628Z.dump`，时间是 2026-11-08 22:06（America/Denver）。
- **额外风险**：main 的 `grants.sql`（每次 compose up 都由 db-roles 执行）会把属主名下**所有**非系统 schema 的表级 DML 授给 aia_api 和 aia_ingest。只要 `ingest_private` 归库属主所有，下一次 up.sh 就会把它开放给 aia_api，破坏 0029「只给 aia_ingest」的设计。这一点要在评审 0029 时核对，并在 grants.sql 里加排除项。

## 9. 各路径比较

| 路径 | 能否过启动检查 | 前置条件 | 风险 | 结论 |
|---|---|---|---|---|
| (a) 等 tb-T-B99e 推上来，评审 0029，按结论**只把迁移文件**入链（休眠）或降级 | 入链后可以（0029 在链里） | 源码推到远端；架构师评审；P3 已合入（0029 的 `down_revision` 应为 0028）；grants.sql 排除 ingest_private | 低：不写用户库，只加一个现有代码不用的迁移文件；风险集中在 0029 是否改动了现有对象 | **推荐** |
| (b) 用户电脑代码回滚到 e3c15aa 或类似版本 | **不能**：e3c15aa 的链只到 0028，库是 0029，照样拒启（已复核）。team-b 的任何提交都一样 | 无意义 | e3c15aa 还带着 T-B99/T-B102 代码：`DAILY_HTTP_LIMIT=3`、`enforce:false`、`live.check_egress→myip.ipip.net`（已在 e3c15aa 上核实）。在 replay 模式下这些不外呼，但全部是搁置项 | 否决 |
| (b') 回滚到 T-B99e worktree 代码（唯一包含 0029 的代码） | 可以 | 访问用户电脑 | 会重新启用未评审、已冻结的共享门禁和证书绑定代码，以及名单 3 次、myip 等搁置项；代码不在任何分支里，无法复核 | 不推荐，只作最后手段 |
| (c) 用 0029 的 downgrade 降到 0028 | 降完后，含 0028 的代码（main 加 P3，≥f20fd83）可以启动 | 先拿到源码并评审 downgrade；db-backup.sh 加恢复演练；停掉 api/worker/ingest；用户批准 | 中：写用户库，会删掉 ingest_private 和那条活绑定（T-A57 认为可以重建）。降级脚本本身需要评审，**不能降到 0027**（库里可能有 false 行，0028 守卫会拒绝） | 作为 (a) 的备选：评审发现 0029 改动了现有对象时用 |
| (d1) 加一个只放行 0029 的临时开关 | 可以 | 改启动检查代码 | 直接违背 T-A14「只读守卫，不 stamp、不放行」的不变量；代码会在一个它不认识的 schema 上运行；开关一旦存在就可能被长期使用 | 否决 |
| (d2) `alembic stamp 0028`，不回退 schema | 可以 | 手工改版本号 | 等于伪造版本：库里留下未知对象（RLS、可能还有触发器），以后再升 0029 会因对象已存在而失败或行为错乱；违背「no automatic stamp」 | 否决 |
| (e) 用 T-O45 的备份恢复到 0029 之前 | 可以（库回到 0028） | 用户批准 | 丢失 2026-11-08 22:06（America/Denver）之后的全部写入（T-B05 实测、用户操作、T-T31 复验等） | 只作最后手段 |

## 10. 推荐的最小路径（(a) 休眠入链，(c) 备选）

| 步 | 内容 | 执行角色 | 需要用户本人批准 |
|---|---|---|---|
| 0 | **冻结**：在用户电脑上不重启、不执行 up.sh/compose up、不 `down -v`，worker/ingest 保持现状，`MAIRUI_MODE` 保持 replay。现在用户电脑离线，要等它上线 | 编排者通知所有人 | 无，属于既有禁令 |
| 1 | **备份**：在用户电脑上执行 `deploy/scripts/db-backup.sh`，然后对该 dump 执行 `db-restore.sh <dump> --db aia_restore_check` 演练恢复，记录 sha256 | 运维 | **是**（访问用户电脑） |
| 2 | **取回 0029 源码**：把用户电脑 T-B99e worktree 的分支推到远端 `tb-T-B99e`，只推不合 | 运维或后端（编排者安排） | **是**（访问用户电脑、推送） |
| 3 | **只读评审 0029**，逐项核对：`down_revision` 是否为 0028；建了哪些对象；有没有改动 app、market、ops 已有表或触发器；RLS 和 GRANT 是否只给 aia_ingest；有没有 SECURITY DEFINER；downgrade 是否完整、库非空时怎么处理；`alembic check` 和 include_object 会不会误报；与 main 的 grants.sql 循环授权是否冲突 | 架构师 | 否 |
| 4a | **评审结论：0029 自成一体**（只新建 ingest_private，不动已有对象）：<br>① 先完成 P3；<br>② 后端用 `cherry-pick -x` 拣入**只含 0029 迁移文件**的提交（必要时拆出），再 amend reset-author，不带任何 T-B99e 应用代码；<br>③ 运维改 grants.sql 排除 ingest_private，并在 verify-roles 里加 api/maint 对 ingest_private 的 permission denied 反例；<br>④ 测试在隔离 PG 上跑 0028↔0029 往返（同第 6 节 A 段）、verify-roles 和 tb95；<br>⑤ 推送 | 后端、运维、测试、架构师 | **推送**要批准 |
| 5a | **部署到用户电脑**：先执行第 1 步的备份，再把代码切到 main（含 P1、P3 和 0029 文件，P2 已合入则一并带上）。启动检查通过，因为 0029 在链里；**不写库**，也不执行 upgrade（已经是 head） | 运维 | **是**（访问用户电脑、部署） |
| 4c | **评审结论：0029 改动了已有对象，或者不宜入链**：在用户电脑上停掉 api/worker/ingest（`docker compose stop`，**绝不 down -v**），用 T-B99e 代码起一次性 migrate 容器执行 `alembic downgrade 0028`。注意不是 0027，0028 守卫可能拒绝。然后部署 main 加 P3（≥f20fd83）启动 | 运维（架构师现场核对清单） | **是**（访问用户电脑、降级数据库、部署） |
| 6 | **验收**：`alembic current` 符合预期；api 健康检查返回 200；风控 GET 正常；`ingest_private` 的行数和 ACL 符合评审结论；全程真实麦蕊调用为 0 | 测试 | 否 |
| 回退 | 如果 5a/4c 任一步失败：停止，用第 1 步的 dump 恢复到新库，验证后切换；**不执行 `down -v`，不删卷** | 运维 | **是**（恢复数据库） |

**为什么推荐 (a)**：这是唯一一条在恢复 API 时不写用户库的路径，也不重新启用任何搁置项（只带迁移文件，不带 T-B99/T-B102 代码）。代价是要先完成 P3，因为 0029 接在 0028 后面，所以 P3 在关键路径上，建议 P3 先于 P2 执行。

**用户能看到的差异**：如果部署 main 时 P2 还没合入，用户会暂时失去 team-b 期间加的搜索、管理员列表和证券详情（T-B94/T-B97/T-B100）以及 T-F33/F34 前端改动，因为这些都在 P2/P4 里。是否接受这段功能退化，或者等 P2 一起部署，需要用户决定。

# 三、未决

1. 0029 的全部内容都没有复核（源码不在仓库里），第 8 节对 0029 的描述来自 T-O45 自报。
2. aia_ingest 对 app 全表都有 DML，这是既有的宽授权，不属于 P3 范围，建议另外派单收紧到最小权限。
3. `selfchecks/test_ta14_migrations.py` 写死了 head=0022，在 main 上就已经失败，是既有问题，建议另外派单。
4. 现在用户电脑离线，第 10 节凡是要访问用户电脑的步骤，都要等它上线并经用户批准。

DeepSeek：用了，用在 P3 共 8 个提交的 numstat 汇总和文件到角色归属表（第 2 节），模型 deepseek-chat（接口返回的 model 字段为 deepseek-flash）。只发送了 `git show --numstat` 元数据和目录规则；结果逐项复核，8/8 一致。RV-01 纠正、恢复路径和验收口径都没有交给它。
