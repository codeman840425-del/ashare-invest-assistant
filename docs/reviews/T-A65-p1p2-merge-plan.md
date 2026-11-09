# T-A65 P1/P2 合入评审方案（接 T-A64 5944ed1）

> 架构师，2026-11-09（America/Denver）。范围只限 T-A64 第 5 节的第 1、2 批（P1 7 个提交，P2 7 个提交，另加 1 个前置提交和 1 个修正提交）。
> 本任务只读：试 apply 只在临时 worktree 里用 `git apply --3way` 做，不 cherry-pick、不提交、不改分支，用完已删除。没有起数据库或容器，没有碰用户电脑，没有调麦蕊。
> T-A64 的三项搁置不在本方案内，执行时也不得顺带引入：名单额度 1→3、`send_governance.enforce:false`、`myip.ipip.net`。0029 也不在本方案内。

## 0. 摘要

| 批 | 顺序（执行人） | 推送点 |
|---|---|---|
| P1 | e56aeec → b714df8 → 21c67fe → 3e6d4dd → c2f519f → 4a3fdc0 → e12bef9，**全部由架构师执行**。前 3 个要改名，T-A48/T-A49 改为 TB-A48/TB-A49 | P1 推送点 |
| P2 | f0ffa52（运维）→ b4092f3（后端）→ 009e2d7（后端）→ **新增修正提交（后端，修 mypy）** → **3e2c7c3（研究员前置，经编排者）** → 1227b65（后端）→ 41d4ee9、ce45025（架构师）→ e5d4a0d（后端） | P2 推送点 |

试 apply 已验证，按上面顺序在 bbcbf66 上全部无冲突。本次新发现两个阻断点，都写进了 P2 流程：
1. **009e2d7 新增 4 个 `mypy --strict` 错误**，都在 `app/master/terms.py`：pypinyin 的 `errors` 回调返回了 list。main 基线本来就有 7 个错误，叠加后变成 11 个。
2. **1227b65 的 `test_importer_module_executes_three_card_golden_preflight` 依赖 `docs/strategies/cards/st_pullback_ma.md`**。这个文件来自研究员的 3e2c7c3（原属 P5）。缺了它测试 1 例失败，加上后 19 过、0 败。

## 1. 通用执行规范（所有人都适用）

1. **只在集成 worktree 上操作**：由编排者指定 `/workspace/wt-integ-teamb`，从本地 main 新建分支 `integ/teamb-p1`（P1）或 `integ/teamb-p2`（P2，基于 P1 推送后的 main）。各角色按第 3、4 节的顺序**依次接力**，同一时刻只有一个人提交。不要直接在共享主树上 cherry-pick。
2. **作者身份**：执行前确认 `git config user.email` 是 `258311554+codeman840425-del@users.noreply.github.com`。`git cherry-pick` 本身不支持 `--reset-author`，所以统一用下面两步：
   ```bash
   git cherry-pick -x <hash>
   git commit --amend --no-edit --reset-author
   ```
   需要改名或补修的提交，在 cherry-pick 之后先改文件、`git add`，再 `git commit --amend --reset-author`，提交信息里保留 `(cherry picked from commit …)` 行。执行后用 `git log -1 --format='%an <%ae>%n%b'` 确认作者不是个人邮箱，并且 -x 行还在。
3. **跨目录提交不拆**：拆开会破坏 -x 溯源。由牵头角色整提交拣入，非牵头目录的部分由对应角色复核签字，见第 2 节。
4. **每个提交拣入后都要跑**：`git diff --check HEAD~1 HEAD`，以及对本提交文件做扫描：
   `uv run --no-project --with pyyaml==6.0.3 python scripts/ci/secret_scan.py files $(git diff --name-only --diff-filter=AMR HEAD~1 HEAD)`。阻断数必须是 0。
5. **残留模式扫描**（每批结束时一次）：
   `git diff --name-only --diff-filter=AMR main...HEAD | xargs rg -n '[A-Z]:\\|Administrator|/home/[a-z0-9_]+|@gmail|\b(?:\d{1,3}\.){3}\d{1,3}\b'`。命中项逐条判断：127.0.0.1 回环、文档保留段地址（192.0.2.x、203.0.113.x）和 `<用户>` 占位都可以放行；其他一律脱敏。
6. 冲突时**停下来交架构师**，不要用 `-X theirs/ours`，也不要跳过。

## 2. 文件到角色的归属表（DeepSeek 机械整理，已全量复核）

规则：`src/backend/**` 归后端；`src/frontend/**` 归前端；`deploy/**`、`scripts/ci/**`、`.github/**` 归运维；`tests/**` 归测试；`docs/strategies/**` 归研究员；其余 `docs/**` 归架构师。

| 提交 | +/- | 文件（角色） | 牵头 | 会签 |
|---|---|---|---|---|
| e56aeec | 101/0 | handover/team/reports/T-A48.md、reviews/T-A48-horizon-ruling.md（架构师） | 架构师 | 无 |
| b714df8 | 10/2 | api-contract.md、plan.md、reports/T-A49.md（架构师） | 架构师 | 无 |
| 21c67fe | 43/2 | plan.md、reviews/T-R24-promotion-gates-ruling.md（架构师） | 架构师 | 研究员知会（内容是 T-R24 卡片门槛） |
| 3e6d4dd | 13/1 | api-contract.md、reviews/T-B94-master-as-of-ruling.md（架构师） | 架构师 | 后端知会 |
| c2f519f | 13/0 | reports/T-O39.md（架构师） | 架构师 | 无 |
| 4a3fdc0 | 13/0 | reports/T-O41.md（架构师） | 架构师 | 无 |
| e12bef9 | 17/12 | reports/T-O41.md（架构师） | 架构师 | 无 |
| f0ffa52 | 97/0 | deploy/scripts/compose.sh、compose-guard-selftest.sh（运维）；reports/T-O40.md（架构师） | **运维** | 架构师复核报告 |
| b4092f3 | 906/2 | api/v1/__init__.py、admin.py、securities.py、master/search.py、selfchecks/test_tb94_routes.py（后端）；reports/T-B94.md（架构师） | **后端** | 架构师复核报告和契约 §7.3/§7.9 |
| 009e2d7 | 582/1 | cli/calendar_seed.py、master_bootstrap.py、security_search_terms.py、master/sync.py、terms.py、pyproject.toml、uv.lock、selfchecks/test_tb97_terms.py（后端）；reports/T-B97.md（架构师） | **后端** | 运维复核依赖和锁文件（第 5 节） |
| 3e2c7c3 | 498/2 | strategies/cards/st_pullback_ma.md、strategies/first_batch_import.md、strategies/T-R16/S-01_st_pullback_ma.md（研究员）；reports/T-R25.md（架构师） | **研究员**（编排者安排，架构师不代提） | 架构师复核 T-R25.md |
| 1227b65 | 453/0 | api/v1/securities.py、cli/cards_import.py、master/profile.py、selfchecks/test_tb100_delivery.py（后端） | **后端** | 无 |
| 41d4ee9 | 20/0 | reports/T-B100.md（架构师） | 架构师 | 无 |
| ce45025 | 1/1 | reports/T-B100.md（架构师） | 架构师 | 无 |
| e5d4a0d | 166/6 | probes/README.md、run_all.py、tb86_history.py、selfchecks/test_tb86_history.py（后端）；reports/T-B96.md（架构师） | **后端** | 架构师复核探针边界（不新增外呼） |

复核记录：DeepSeek 整理了 P1/P2 的 14 个提交。其中 13 个与 `git show --numstat` 完全一致；009e2d7 的新增行数它算成了 586，实际是 582，表中已按实际值修正。角色判定 14/14 正确。前置提交 3e2c7c3 那一行是我自己整理的。

## 3. P1 逐提交执行单（全部由架构师执行）

改名建议：team-b 的 T-A48/T-A49 和我方已用编号（交接小单，见 main 历史 9ba7164、a0e5498）撞号。统一改成 **TB-A48 / TB-A49**，TB 表示 team-b。这样保留和 team-b 历史及 HANDBACK 的对照关系，也不占用我方 T-A 序号。如果编排者更愿意用新序号，备选是 T-A66/T-A67，并在正文首行注明「原 team-b T-A48/T-A49」。替换安全性已核实：main 的 docs/ 里没有任何 `T-A48`/`T-A49` 字样，所以只在相关文件内整词替换即可。

| 序 | 提交 | 操作 | 预计冲突 | 改名/脱敏 |
|---|---|---|---|---|
| 1 | e56aeec | pick 后执行 `git mv docs/handover/team/reports/T-A48.md docs/handover/team/reports/TB-A48.md`、`git mv docs/reviews/T-A48-horizon-ruling.md docs/reviews/TB-A48-horizon-ruling.md`，再对这两个文件执行 `sed -i -E 's/\bT-A48\b/TB-A48/g; s/\bT-A49\b/TB-A49/g'`，然后 amend | 无 | 改名；不需要脱敏 |
| 2 | b714df8 | pick 后 `git mv …/T-A49.md …/TB-A49.md`；对 `docs/plan.md`、`docs/api-contract.md`、`TB-A49.md` 执行同一条 sed；amend | plan/契约是热点文件，main 如果先动过，可能在 §2.5.11A / §7.11.3 附近冲突（试 apply 无冲突） | 改名 |
| 3 | 21c67fe | pick 后对 `docs/reviews/T-R24-promotion-gates-ruling.md`、`docs/plan.md` 执行同一条 sed；amend | 同上（plan §2.5.0B/§2.5.13） | 改名（正文引用） |
| 4 | 3e6d4dd | 直接 pick 加 reset-author | 契约 §7.3 一行 | 无 |
| 5 | c2f519f | 直接 pick | 无 | 已打码（`C:\Users\...\`，127.0.0.1 是回环），不用改 |
| 6 | 4a3fdc0 | 直接 pick | 无 | 无 |
| 7 | e12bef9 | 直接 pick | 无（只改上一步的 T-O41.md） | 无 |

P1 结束后检查 `rg -n '\bT-A4[89]\b' docs` 应该是 0 处，`rg -n 'TB-A48-horizon-ruling' docs` 应该有 4 处，引用全部指向已改名的文件。试 apply 时这两项都已复现。
后续提醒：P5 里研究员的 T-R24.md、T-R25.md、card_promotion_gates.md、first_batch_import.md 也引用了 T-A48，研究员拣入时要用同一条 sed。

## 4. P2 逐提交执行单

| 序 | 提交 | 执行人 | 操作 | 预计冲突 | 脱敏 |
|---|---|---|---|---|---|
| 1 | f0ffa52 | 运维 | pick 加 reset-author；跑 `bash -n deploy/scripts/compose.sh && bash deploy/scripts/compose-guard-selftest.sh` | 无 | T-O40.md 用的是 `<用户>` 占位，可以放行 |
| 2 | b4092f3 | 后端 | pick 加 reset-author | `api/v1/__init__.py` 的路由注册行（试 apply 无冲突） | 无 |
| 3 | 009e2d7 | 后端 | pick 加 reset-author；按第 5 节检查依赖 | `pyproject.toml`、`uv.lock` 在依赖段可能冲突（试 apply 无冲突）。如果冲突，**不手工合并 lock**，改为重新执行 `uv lock` 后再复核 | 无 |
| 4 | （新增）| 后端 | 新提交 `fix(master): T-A65 type pypinyin errors callback`：修 `app/master/terms.py` 里两处 `errors=lambda chunk: list(chunk)` 引起的 arg-type/return-value 错误。可以包一层显式类型的回调，或者在调用处加带理由注释的 `# type: ignore[arg-type]`，**不改行为** | 无 | 无 |
| 5 | 3e2c7c3 | **研究员**（编排者安排） | pick 加 reset-author；对 first_batch_import.md、T-R25.md 执行第 3 节同一条 sed。这是 1227b65 测试的前置 | 无 | 无（虚构示例代码） |
| 6 | 1227b65 | 后端 | pick 加 reset-author | `api/v1/securities.py`，叠加在序号 2 之上（试 apply 无冲突） | 无 |
| 7 | 41d4ee9 | 架构师 | 直接 pick | 无 | `/tmp/tb100_source` 是通用临时路径，可以放行 |
| 8 | ce45025 | 架构师 | 直接 pick | 无 | 无 |
| 9 | e5d4a0d | 后端 | pick 加 reset-author | `probes/tb86_history.py`、`run_all.py`（main 上 T-B99 没有进来，试 apply 无冲突） | T-B96.md 只有 `~/.local/state/...` 这类通用路径，可以放行 |

如果研究员不同意提前拣入 3e2c7c3，P2 改为暂缓 1227b65、41d4ee9、ce45025 三个提交，其余照常。**不得**为了让测试通过而改测试或跳过测试。

## 5. 依赖 pypinyin 的检查要求（009e2d7，运维复核签字）

1. **版本固定**：`pyproject.toml` 写的是 `"pypinyin==0.55.0"`（已核实）。uv.lock 里 requires-dist 是 `==0.55.0`，package 段为 0.55.0。
2. **哈希一致**：uv.lock 里 wheel 的 sha256 是 `d53b1e8a…a286f`，sdist 的是 `b5711b3a…aa66b`。这两个值必须与 PyPI 上 0.55.0 的发布文件一致；本次已用 PyPI JSON 元数据核对过，一致，执行时再核一次。
3. **锁文件新鲜**：在 `src/backend` 下执行 `uv lock --check`，必须报告 lock 是最新的；本次离线试跑结果是 Resolved 53 packages，无变化。然后 `uv sync --frozen` 必须成功。不允许手改 lock。
4. **许可证**：PyPI 元数据显示 MIT（`License :: OSI Approved :: MIT License`）。执行 `python3 scripts/ci/check_licenses.py --python src/backend/.venv/bin/python`，必须是「禁止类 0，未识别 0」，本次试跑结果符合。
5. **漏洞和来源**：PyPI 的 `vulnerabilities` 为空，没有 yank。依赖是纯 Python 包（py2.py3-none-any），没有原生扩展，也没有安装钩子。不得引入额外的拼音词库包，比如 pypinyin-dict。
6. **运行时**：只有 `app/master/terms.py` 导入它，在显式 CLI 或 `--rebuild-search-terms` 时才运行，不联网。

## 6. 定点测试范围（命令都在 `src/backend` 下执行，清空证书环境变量）

通用前缀：`env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY`，离线项建议再加 `unshare -rn`（断网）。

**P1**（文档）
- 仓库根目录执行 `uv run --no-project --with pyyaml==6.0.3 python scripts/ci/check_contract.py`，必须「契约文档对照通过」。
- 第 3 节末尾的 rg 检查。

**P2 静态检查**
- `uv run --frozen ruff check .`
- `uv run --frozen mypy`：错误集合必须**不多于 main 基线**（当前基线 7 个，都不在 P2 文件内）。验收看「新增 0 条」，不看总数为 0。
- 仓库根目录执行 `bash deploy/scripts/compose-guard-selftest.sh`，必须 3 passed。
- 第 5 节的依赖检查。

**P2 离线自检**（不需要 PG）
- `uv run --frozen pytest -q selfchecks/test_tb86_history.py selfchecks/test_tb94_routes.py selfchecks/test_tb97_terms.py selfchecks/test_tb100_delivery.py`。试跑结果（含 3e2c7c3）：19 过、21 跳过、0 败。
- `uv run --frozen python -m probes.tb86_history --preflight-only --counter <临时不存在路径> --secret-path <临时不存在路径>`：输出必须是 `new_calls: 0`，而且不读证书。

**P2 隔离 PG 自检**（由运维准备，由测试执行并签字）
- 用 compose 同款镜像 `timescale/timescaledb:2.31.0-pg16@sha256:322ae364…` 起一次性库，只绑定 127.0.0.1：
  - tb94：端口 55494，库 `tb94_test`
  - tb97：端口 55497，库 `tb97_test`
  - tb100：端口 55498，库 `tb100_test`
- 用 `alembic upgrade head` 升到 0027。tb94 会断言 `alembic_version=0027`。
- 设置 `TB94_ISOLATED_DATABASE_URL`、`TB97_ISOLATED_DATABASE_URL`、`TB100_ISOLATED_DATABASE_URL`，值分别**严格等于**测试文件里的 DSN：`postgresql+psycopg://postgres@127.0.0.1:<端口>/<库>`。
- 再跑一遍上面的离线自检命令，跳过数必须是 0。
- 测完删除容器和卷。**不得**连用户库或运行栈的库。
- 前端：P1/P2 没有前端文件，不用跑。

## 7. 验收口径

**通过**（全部满足才算）
1. 每个提交的作者都是 noreply 身份，都带 `cherry picked from commit` 行，顺序与第 3、4 节一致。
2. 每个提交扫描阻断都是 0，`git diff --check` 无输出；残留模式扫描没有未放行的命中。
3. `check_contract.py` 通过；`rg '\bT-A4[89]\b' docs` 为 0。
4. ruff 通过；mypy 相对基线新增 0 条；compose 守卫自测 3/3 通过。
5. pypinyin 第 5 节 1–5 项全部满足。
6. 离线自检 0 败；隔离 PG 自检 **0 败、0 跳过**（tb94 8 例、tb97 4 例、tb100 9 例都要实际执行）。
7. `git diff main...HEAD --stat` 里没有 `app/ingest/`、`config/ingest.yaml`、`deploy/compose/`、`src/backend/migrations/` 的改动，确认搁置项和 0028/0029 都没有混进来。

**失败**（任一出现就不推送，回到架构师）
- 有冲突，或者需要手工改业务代码（第 4 节序号 4 的类型修正除外）。
- 任何测试失败、隔离 PG 用例被跳过，或者为了通过而修改、跳过测试。
- mypy 新增错误、锁文件不新鲜、许可证命中禁止类或无法识别。
- 出现真实路径、用户名、IP、邮箱、证书或样本。
- 变更范围超出本方案列出的提交。

## 8. 推送点和推送前条件

- **P1 推送点**：第 7 节第 1–3 条满足后，编排者把 `integ/teamb-p1` 快进到本地 main（`git merge --ff-only`），由运维扫描并汇总 hash。**推送前要用户确认**，然后由运维执行 `git push origin main`，不 force。推送后执行 `git ls-remote origin main`，确认远端 hash 等于本地 hash。
- **P2 推送点**：从 P1 推送后的 main 新建 `integ/teamb-p2`，第 7 节第 1–7 条全部满足；研究员已确认 3e2c7c3；测试已签字隔离 PG 结果；运维已签字依赖检查。之后同样经用户确认，ff-only 后推送并核对远端。
- 两批之间如果 main 有新提交，先 `git rebase main integ/teamb-p2`，只限未推送的集成分支，再重跑第 6 节全部检查。
- 不推 team-b，不改 team-b，不删 team-b 上的任何分支。

## 9. 本次试 apply 记录（临时 worktree，已删除）

- 基线 origin/main=bbcbf66。P1 7 个提交依次 `git apply --3way` 无冲突；按第 3 节改名和 sed 之后，`T-A4[89]` 残留 0，契约检查通过，扫描 9 个文件阻断 0。
- 接着 P2 7 个提交无冲突，扫描 36 个文件阻断 0，`diff --check` 无输出；`ruff check .` 通过；compose 守卫 3 passed；`uv lock --check --offline` 无变化；check_licenses 禁止类 0、未识别 0；mypy 新增 4 条（terms.py）。
- 离线自检：不加 3e2c7c3 时 1 败（缺卡片文件）；加上后 19 过、21 跳过、0 败。tb86 preflight 在台账缺失时输出 `offline_controls_not_ready`、`new_calls 0`，属于 fail-closed。
- 隔离 PG 用例：本次没起库，**未执行**，由第 6 节的执行人完成。

## 10. 风险和未决

1. 3e2c7c3 原属 P5，提前拣入需要研究员确认，我方架构师不代提。
2. mypy 基线本身就有 7 个错误，CI 的 mypy 步骤可能早已是红的。本方案只要求不新增；基线问题请编排者另外派单。
3. plan.md 和 api-contract.md 是热点文件，P1 执行前 main 如果有新文档改动，第 2、3 步可能冲突，冲突就交架构师处理。
4. TB-A48/TB-A49 改名会让 team-b 原 HANDBACK 里的编号与 main 不一致。P6 重写 HANDBACK 时要加一张对照表。

DeepSeek：用了，用在 P1/P2 共 14 个提交的 numstat 汇总和文件到角色归属表（第 2 节），模型 deepseek-chat（接口返回的 model 字段为 deepseek-flash）。只发送了 `git show --numstat` 元数据和目录规则。结果已全量复核，修正了 1 处行数（009e2d7 是 582，不是 586）。执行顺序、阻断点和验收口径都没有交给它。
