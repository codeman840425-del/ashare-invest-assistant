# 评审 9e693b2（T-B49b）

- 评审人：项目架构师；时间：2026-11-01 20:35（America/Denver，UTC-7）
- 方式：只读。干净导出 git archive 9e693b2，后端 `uv sync --frozen`；临时容器 rv1101-pg（timescale pg16）、rv1101-redis 只绑 <host>；跑了 deploy/db/roles/apply-roles.sh，角色口令是一次性随机 hex，不是任何环境的真实值。没有推送，没有调用麦蕊。
- 对照：plan 3.5（导入）、契约 v0.2.9 #27/#32/#35、T-T25-rulings.md、review-6670b10.md、review-66f1906.md、review-82b612b.md、T-live-83a031c §8 裁定。

## 结论：可以推送（有条件）

没有阻塞项。review-6670b10 的 M1（冷却用 DB 时间）、M2（触发器白名单）、m2（ETF 空串）都修好了，0018 迁移的安全性也实测过。剩下两个主要问题不是本提交新引入的，但都没修：放弃批次时提前删除原始文件（M1，3e5e288 声称已修，未评审）；horizon 结果落库（M2）。推送后 contract 任务是红的，要连推到 d3be426 才会转绿。

## 1. 实测

| 项 | 结果 |
|---|---|
| ruff / mypy（104 个文件） | 通过 |
| selfchecks/tb49b.py（真实 PG + Redis，已应用角色） | **62 passed / 0 failed** |
| selfchecks/tb49.py | 79 passed（第一次因 aia_maint 不存在而失败，跑完 apply-roles.sh 之后通过） |
| selfchecks/g7.py | 22 passed |
| selfchecks/tb48_p11.py | 没跑：venv 里缺 `requests`（ModuleNotFoundError），属于自检环境问题，不是本提交引入 |
| alembic up → down → up + `alembic check` | 通过，"No new upgrade operations"（注意：alembic check 不比较 CHECK 约束的内容） |
| 0018 降级时库里有 on_demand 行 | 拒绝：`RuntimeError: 0018 降级拒绝：symbol_horizon_assessments 中有 1 行 trigger='on_demand'…`，版本停在 0018 ✓ |
| 删掉那行后再降级 | 成功；0017 的 CHECK 会拒绝 on_demand ✓；再升级回去成功 ✓。预检查和改约束之间存在竞态，但 ADD CONSTRAINT 本身会校验已有行，所以是安全的 |
| 删除 CLI 触发器白名单（真实库、0018 head） | 范围内 91 张表，`unknown_triggers = []`，白名单里也没有多余的过期项 ✓ |
| grants | aia_api、aia_ingest 对全部 app 表都有 SELECT/INSERT/UPDATE/DELETE（grants.sql:103），所以按裁定用 aia_api 的 worker DSN 跑清理任务没问题 ✓ |
| check_contract（只看文档）/ check_code_namespaces | rc 0 |
| check_contract --meta-json | **失败**：缺 4 个枚举（plan_status、plan_condition_type、security_reconciliation_kind/source），error_codes 缺 URI_TOO_LONG。d3be426 修好 |
| tester d018fad 套件（跑在 d3be426 上，这部分后端代码与本提交相同） | R6 的 6 个 error 是本提交 R11 #9 收紧 qty/price 类型造成的，属于预期的契约变化，归 tester（见 review-d018fad M3） |

## 2. 逐条核对

| 说法 | 核对 |
|---|---|
| A3 limit ≤ 200 | ✓ 自检：limit=200 → 200；配置 page_limit_max > 200 时拒绝启动 |
| B1 0018：trigger CHECK 加 on_demand，降级有预检查 | ✓（实测见上） |
| B2 删除 CLI 触发器白名单 | ✓ app/cli/delete_user_data.py:416 TRIGGER_ALLOWLIST、:519 _scope_tables、:524 _TRIGGERS_SQL、:537 unknown_triggers。dry-run 列出差异；`--execute` 在确认之前就退出 1；没有跳过开关 ✓。范围外的触发器（engine_policies 等）CLI 不碰，没问题 |
| B3 冷却按半开区间、用 DB now() | ✓ app/licences/service.py:227 db_now 用 func.now()，判定是 `paused_until <= ref`；set_licence（:352）、delete_licence（:472）都用 db_now；自检包含相等边界和 +1µs 两种情况 ✓ |
| B5 R11 #9/#10 收紧 schema | ✓（trades 的 qty/price 必须是字符串，imports 的 encoding_override 收紧）；tester 要跟进 |
| B6 计划草稿数量截断 | 只做了辅助函数：app/market_rules/lots.py:156 clamp_draft_qty 没有调用方（plan-drafts 接口还没有）→ m3 |
| §8 裁定：放弃/失败批次的预览行在同一事务里删除，并有每小时清理任务 | 同一事务 ✓（discard 在 imports.py:799；run_parse 失败路径见 pipeline.py:366–378，只在 rowcount 不为 0 时删）；ROWS_DROPPED_STATUSES = ("discarded","failed") ✓；任务幂等 ✓。分段提交、任务名见 m1、m2 |
| ETF data_source 为 "" 或空白 → T+1 | ✓（review-6670b10 m2 已修；tester 的 12 个 ETF 用例转为 XPASS） |

## 3. 问题

**B：无。**

**M**
- **M1 放弃批次时提前删除原始文件（这个行为不是本提交引入的，但本提交改了同一函数却没修）。** src/backend/app/api/v1/imports.py:800–808：discard 把 import_files 的 deleted_at 设为 now、storage_path 设为 None，提交后调 `storage.delete_raw`。这违反 plan 3.5（"原始文件不因放弃或失败而提前删除"）和契约 #35 / T-B56。修法：discard 只改批次状态、删预览行，原始文件留到 retained_until，由到期清理任务删除。3e5e288 声称已修，但还没有评审。→ 后端
- **M2 horizon 结果仍不落库（T-T25 #7 / 契约 #27 ⑧）。** GET /horizon-assessments 不写 symbol_horizon_assessments；snapshot_id 是 uuid5 算的（app/strategy/horizon/inputs.py:168），不是 data_snapshots 里真实的 id。0018 只放开了 CHECK。修法：按 on_demand 写入，snapshot_id 指向 purpose=horizon、带 user_id 的真实 data_snapshots 行，同输入复用同一条记录。→ 后端（T-B30a / T-B47-x）

**m**
- m1 src/backend/app/importing/pipeline.py:352 purge_uncommitted_import_rows 是一条没有上限的 DELETE。plan 3.5 要求"按批次分段提交，每次最多处理 10,000 行"。修法：按批次循环，每段 ≤ 10,000 行就提交一次。→ 后端
- m2 任务名不一致：jobs.py:48 是 `imports.purge_uncommitted_rows`，plan 写的是 `imports.purge_preview_rows`（3e5e288 声称已改名，未评审）。→ 后端
- m3 clamp_draft_qty（lots.py:156）没有调用方；plan-drafts 落地时必须接上，并补接口层用例。→ 后端
- m4（nit）service.py:453 的 updated_at 仍用 now_utc()，同一行里混用了应用时钟和 DB 时钟。不影响冷却判定，建议统一用 db_now。→ 后端
- m5（上次 m3 遗留）0017 降级没有显式预检查。本提交没修；fb4104a 声称已修，未评审。→ 后端

## 4. 上次评审的 M/m 是否修复

| 来源 | 项 | 状态 |
|---|---|---|
| review-6670b10 M1 冷却用 DB 时间 | 已修 ✓ |
| review-6670b10 M2 触发器白名单 | 已修 ✓ |
| review-6670b10 M3 /meta/enums | d3be426 已修 ✓ |
| review-6670b10 M4 T-T25 剩余项 | 部分修：0018、schema 收紧、截断辅助函数已做；horizon 落库没做（本报告 M2） |
| review-6670b10 m1 /portfolio fresh/stale | 本提交没修（portfolio.py:424–427 有价就是 STALE）；fb4104a 声称已修，未评审 |
| review-6670b10 m2 ETF 空串 | 已修 ✓ |
| review-6670b10 m3 0017 降级预检查 | 没修（本报告 m5） |
| review-6670b10 m5 cooldown-purge 服务 | 不在本提交；028c077 已删除，worker DSN 按裁定用 aia_api |
| review-66f1906 M1 precision_only | 不在本提交。d3be426 的 probes/p11_gaps.py:242 仍是宽松判定（例如 20.0 和 19.6 取 k=0 会判为 True）；f065f8d 声称已改为严格判定，未评审 |
| 裁定：JSON 格式错误应先返回 401 | 没修（d3be426 实测：匿名请求格式错误的 JSON 返回 400）。归 T-B50；fb4104a 声称已修，未评审 |

## 5. 推送后 CI

| 任务 | 结果 | 归属 |
|---|---|---|
| backend：ruff / mypy | 绿 | — |
| backend：pytest | 取决于 tests/backend 是否已在 main。T-T01 合入后，按 review-d018fad 的 M1–M4 会红（KNOWN_HEADS、R6 的 qty 类型、meta 错误码计数、securities 快照） | tester |
| contract --meta-json | **红**：缺 4 个枚举和 URI_TOO_LONG | 后端，d3be426 修复 |
| migrations up/down/up/check | 绿（本机实测） | — |
| frontend | 不涉及 | — |

## 6. 谁做什么
- 后端：M1、M2、m1–m5；JSON 格式错误先返回 401（T-B50）。
- tester：按 review-d018fad 处理，KNOWN_HEADS 加 0018/0019，R6 夹具改为发字符串；摘掉 12 个 ETF 用例的 xfail。
- 运维：上共享库之前，按 0018 的降级说明确认没有 on_demand 行需要人工处理（升级不需要预检查）。
