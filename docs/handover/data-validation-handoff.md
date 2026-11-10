# 数据验证交接手册（T-A110）

> 2026-11-10 America/Denver。基线 `origin/main=e44311a018270d4db2c111ca04015ff3b86c10a8`。只改 `docs/`（不含 `docs/strategies/`）。
>
> 给**没有本团队上下文的新团队**续做 G2 剩余键（F21 / F23 / F14 / F15）、T-B86 复跑与 T-B59 补证。新团队在用户 Windows 电脑运行：仓库路径 `F:\ashare-invest-assistant`，分支前缀 `tb-`，团队分支 `team-b`。电脑靠 VPN，可能掉线。
>
> **在用户本人重新授权之前，不得调用麦蕊。** 本团队额度用尽后的交接，不把既有「最多 128 次」授权自动转给新团队。本文不含密钥值、证书值、原始行情、私有样本或股东代码；只写环境变量名与文件路径。

## 0. 怎么用这份文档

1. 先读本节与 §4（须用户本人决定的事项），不要先发请求。
2. 各键的验收口径以仓库内权威文件的 **路径:行** 为准；冲突时新裁定优先于旧描述。
3. 数字、日期、窗口一律来自已查到的文件。写「未查到 / 待编排者补」的，不要编造，也不要自行补跑过窗段。
4. 运行栈必须在 **WSL（Linux）** 里操作，不要用 Windows Git Bash / PowerShell / CMD 调 `compose.sh`（见 §3.1）。
5. G7 代批与 `draft→simulating` **不要改写**，只引用 `docs/reviews/T-A109-g7-delegation.md`（本地分支 `docs/T-A109=ffddab6`，**尚未合入 main**；合入后以该路径为准）。

### 0.1 权威来源

| 主题 | 权威位置（均相对仓库根，行号按 `e44311a`） |
|---|---|
| G2 缺口与实测清单 | `docs/plan.md` :985–996（T-A19 裁定）；清单表在团队报告 `/workspace/team/reports/T-A19.md`（与 `docs/handover/team/reports/T-A19.md` 一致） |
| F14/F15 MVP 改用麦蕊列表 | `docs/plan.md` :987–991（**T-A22**，覆盖 T-A19 原文「0 次麦蕊 / 只走交易所公开列表」） |
| 特征口径与状态 | `docs/strategies/feature_spec.md`（v1.1.14）：F14 :237–244，F15 :254–259，F21 :291–296，F23 :305–310，§7D :922–934，V6/V7 :956–957，汇总 :986–987、:993、:995 |
| T-R18 九键矩阵（含 F21） | `docs/strategies/T-R18_source_matrix.yaml` :16（`f.main_net_20d`） |
| F23 新鲜度/完整性判据 | `docs/strategies/f23_freshness_protocol.md`（T-R26，v1.0）；工具与名单在 `docs/strategies/T-R26/` |
| F21 覆盖就绪（只读，不升级状态） | `docs/strategies/check_f21_ready.py`；阈值锁 `docs/strategies/T-R28/f21_ready_thresholds.json` |
| T-B86 账本与段上限 | `src/backend/probes/tb86_offline.py` :43–54、:83；计数文件见 §2 |
| 唯一出口 | `src/backend/app/ingest/egress.py` `mairui_get` :448 起；契约 `docs/api-contract.md` §7.11.5 约 :1409 |
| Windows / WSL | `docs/runbook/windows-local.md`；`deploy/scripts/compose.sh` :31–40 |
| 证书封装密钥（文件名，不含值） | `docs/handover/private-prerequisites.md` :9、:14–16；`docs/runbook/windows-local.md` :19–37 |
| 解除 HALT / 恢复出网 | `deploy/runbooks/wrapup-deploy.md` :105、:201；`deploy/runbooks/ingest-halt.md` |
| G7 代批（随 T-A109 合入） | `docs/reviews/T-A109-g7-delegation.md`；勿以 `e44311a` 的 `docs/plan.md` :1000 旧「禁止代批」句为现行条款 |

词表重建、`compose.sh` 拒 Git Bash 等部署注意见 T-A106 / T-A107 报告（`/workspace/team/reports/T-A106.md`、`T-A107.md`），不在本单范围，但 Windows 续跑必须遵守 WSL 要求。

## 1. 各键现状

以下「已有证据」只列可引用的提交/文件；gitignored 的原始响应**不要入库**。

### 1.1 F21 `f.main_net_20d`

- **状态**：`declared`（`feature_spec.md` :934、:1054；T-R18 矩阵 :16 `keep_declared` / `live_evidence.task=T-B81`）。单位、大单阈值、盘后定稿时间仍缺证。不得用内置因子 `main_20d_net` 替代四字段和（:292）。
- **验收口径**：
  - 公式与字段：`feature_spec.md` :291–296、:1054；可得时点 d 日 15:40 后（:37、:294）；窗口 20、有效日 ≥15，否则 null（:295）。
  - T-A19 实测清单第 1 项（`reports/T-A19.md` 表）：5 只股，d 日 15:40 后与 d+1 开盘前各取 1 次，对比定稿与单位；该项上限 **12**。
  - 随后账本把 F21 从 12 收到 **10**（5+5），**2 次保持未分配、不挪用**（`tb86_offline.py` :47–52，`f21_trading_window.transaction=10`）。
  - 覆盖就绪检测（不是定稿证据）：`check_f21_ready.py` :1–13、:75–77、:144–171；锁定阈值 `min_stocks=5`、`min_days=15`、`window_days=20`（`T-R28/f21_ready_thresholds.json`）。只读、不升级状态；禁止用环境变量或 CLI 改阈值（:28–35、:56–72）。T-R31 报告：本机无 `DATABASE_URL`，**未做实库扫描**。
- **已有证据**：
  - T-B81（提交 `535f9fc`，已在 `e44311a`）：两只样本、20 个交易日窗口完整，四字段与内置因子不等价；单位/阈值/定稿未闭合。原始响应 gitignored。摘要见 `docs/handover/team/reports/T-B81.md`。
  - T-B86-F21-D（2026-11-10）：d 日 15:40 后 5 次调用已完成，计数 +5，未熔断。任务单 `/workspace/team/tasks/T-B86-F21-D.md`；结果追加在团队报告 `/workspace/team/reports/T-B86.md`（**仓库内** `docs/handover/team/reports/T-B86.md` 仍停在历史段、记 0/128，未含本段）。T-A19 未列代码，任务单采用例行五只（与 T-R26 watchlist 前五只一致）；以任务单与账本 `records[].id` 为准，本文不另抄名单。
- **缺什么**：
  1. d+1（2026-11-11）开盘前第二次取数（任务单写北京 08:20 另派），才能对比定稿与单位。
  2. d 日原始响应目前只在共享电脑 gitignored 目录（团队报告记 `/workspace/wt-be-T-B118/src/backend/probes/results/T-B86-F21-D/`），**未入库**。对比 d+1 需要这些快照：须由编排者经**私密渠道**交给新团队，不得提交仓库。若交不到，d+1 对比无法做完，待编排者补。
  3. 单位 / 特大单与大单阈值 / 盘后定稿时间仍未闭合（矩阵 :16 `gaps`）。
  4. `check_f21_ready.py` 尚未在隔离库/用户库跑出 `ready`/`not_ready`（未查到实库结果）。

### 1.2 F23 `f.ann_risk_count_10d`

- **状态**：仍为 `declared`（协议文首 :4；T-R22 报告：全量验收 failed，不提升级；T-R26 / T-R31：保持 declared）。V7 字段路径已实测（`feature_spec.md` :957），不等于新鲜度/完整性通过。
- **验收口径**：
  - 公式与时点：`feature_spec.md` :305–310；plan T-A19 :992–995；T-R22 裁定 :997（`verified_live` 仍以 T-A19 两项实测为准）。
  - **verified_doc**（词表离线）：plan :993 与 T-R22 裁定①（≥1,000 条不按关键词筛选的标题，误报 ≤5%、漏报抽检 0）。T-R22 未通过。后续冻结词表 v2.1 副本在 `docs/strategies/T-R26/`（协议 :97），**不是**已升 verified_doc。
  - **verified_live**（协议 :11–14、:43–58、:60–80）：
    - Q1 新鲜度：20 只 × 5 个连续交易日，d 日公告在 d+1 北京 09:00 前可取，公告条数命中率 **≥95%**（5 天合并，不按天放行）。
    - Q2 完整性：≥10 条已知风险公告全部取到且冻结词表命中，**漏 0**。
  - 名单与完整性清单：`docs/strategies/T-R26/watchlist20.yaml`、`completeness_list.yaml`。T-R26 报告写明：**名单待架构师确认，清单待编排者确认执行**。未查到后续书面确认。T-B86-F23-D1 任务单已采用 watchlist20，但该段未跑。
  - 每日核对：`docs/strategies/T-R26/daily_check.py`；Windows 须 `PYTHONUTF8=1`（协议 :37）。台账路径 `T-R26/ledger/ledger.jsonl`、证据 `T-R26/evidence/`：在 `e44311a` **尚未建出**（目录不存在），D1 也无取数，故无台账行。
- **已有证据**：词表与离线检查器（T-R22/T-R23/T-R26 文档与冻结哈希，见协议 :97）。无新鲜度/完整性 live 证据。
- **缺什么**：
  1. 架构师确认 20 只名单、编排者确认完整性清单（协议 :18–29、:62、:94–95）。
  2. 新鲜度取数：原协议窗口 D1–D5=**2026-11-09..13**（协议 :5）。编排者因 11-09 已过，改为 **11-10/11/12/13/16** 为 D1–D5（`/workspace/team/tasks/T-B86.md`）。D1（11-10 北京 09:00 前）**未跑、0 次，过窗不补**（`T-B86.md` / `T-B86-F23-D1.md`）。剩余至多 4 天 × 20 次（见 §2 日期表）。
  3. 完整性 10 次取数（第 6 天后，须另派）。
  4. 研究员巨潮公开页真值保全与台账核对（协议 §3；不调麦蕊）。
  5. 两项达标后由架构师决定是否升 `verified_live`（协议 :16）；未达标则保持 declared，不重试、不追加取数（协议 :58）。

### 1.3 F14 `f.is_st` 与 1.4 F15 `f.is_delisting_period`

两键同源、一起验收，分列口径如下。

- **口径（公式/来源/时点）**：`feature_spec.md` F14 :237–244，F15 :254–259；失效与 PIT 见 plan T-A19 :986 及 T-A22 :991。d 日 18:00 快照，d+1 可见；缺失为 null，不回填、不拿旧成功冒充当日。
- **来源裁定（勿沿用 T-A19 表上的「0 次麦蕊」）**：T-B85（`4563d1d`）官方导出返回 `success=false`，立即停止、不补头不换路径；未跑满 1 个交易日。T-A22（`docs/plan.md` :987–991）规定 MVP 改用麦蕊证券列表（`/hslt/list`、`/bj/list/all`、`/kc/list/all`）简称，按 `security_master` §5 推导；`master_snapshots.source = mairui_list`。**每个交易日 18:00（北京）取 1 次，计入麦蕊预算，须用户本人授权后才能实调。** 三个路径在「1 次」里如何计数，文件未写成固定 3，**待编排者补**。回切交易所名单的条件见 :990。
- **verified_doc 验收**（:989）：① 麦蕊文档写明简称字段含义；② 研究员用交易所公开网页（正常浏览，不调接口）人工核对一个交易日：当日全部 ST、*ST、退市整理期证券，加 20 只非风险抽样，与推导结果 **0 不一致**。通过后可写 verified_doc（只到 simulating）。verified_live 仍等更广实测（T-A19 :986 原文「等 T-B05」）。
- **已有证据（实现，非实采）**：T-B85b 提交 `a305d14`（已在 `e44311a`）完成 `mairui_list` 离线快照/差分/PIT 接线；报告写明 **0 次官网/麦蕊调用**，未上线实采（`docs/handover/team/reports/T-B85b.md` 及 `/workspace/team/reports/T-B85b.md`）。
- **缺什么**：用户授权下的首个交易日 18:00 实采；简称字段的文档依据；研究员同日人工核对；历史表在用户已部署实例中有成功快照。未查到任何实采日期或快照行数。

## 2. T-B86 接续

### 2.1 计数文件：位置、格式、已用次数

| 项 | 值（均来自实核，2026-11-10 02:25 America/Denver） |
|---|---|
| 共享电脑活账本（不在仓库） | `/workspace/team/runtime/mairui-batch-T-B86.count`（权限 600） |
| 格式 | JSON，`schema=T-B86/v1`；顶层键仅 `schema` / `total` / `records` / `halted`；每条 record 仅 `id` / `segment` / `interface`（`tb86_offline.py` :114–128） |
| 全批上限 | 128（`TOTAL_CAP`）；CAPS 合计分配 126，预留 2 不挪用（:47–54；历史段报告同此） |
| 当前 | `total=5`，`halted=false`，5 条均为 `segment=f21_trading_window`、`interface=transaction`（id 见入库快照） |
| 入库快照（本单提交） | [`data-validation/t-b86-ledger-summary.json`](data-validation/t-b86-ledger-summary.json) |

此后**不要**再把共享电脑那条绝对路径当 Windows 活账本。Windows 侧活账本路径由新团队在 WSL 工作树外选定（建议 `$AIA_SECRETS_DIR` 的兄弟目录或 `/root/.config/aia/state/mairui-batch-T-B86.count`，**不得**放进仓库、不得写入证书值），并在段标记里记下路径名。

既有机制：加锁、**先 fsync 再请求**、唯一 `id` 防重放、失败也占额度、STOP / HTTP 或业务码 103/429 立即停（`tb86_offline.py` :165–215 及历史段报告）。这只解决「同一 id 不发第二次」，**没有** started/done 两态，也没有摘要哈希；活账本路径还写死在共享电脑。不够 VPN 掉线后的判定，见 §3.5 须新实现的契约（本单不写代码）。

### 2.2 剩余窗口与日期表

交易日已核：`config/trading_calendar.json` 与 `docs/strategies/calendar/trading_calendar_2026.json` 的 `open_days` 均含 2026-11-09..13、11-16，不含 11-14、11-15。

**规则：过窗就跳过、不硬补。** 已用于 F23 的 11-09（原协议 D1）与 11-10（调整后 D1）。过窗次数不得改派给其他键或另加日期，除非用户本人另授权。

| 窗口（北京） | 对应 Denver（UTC-7） | 段 / 计划次数 | 状态 |
|---|---|---|---|
| 2026-11-09 15:45 F21 d；09:00 前 F23 | 11-08 晚 / 11-08 18:00 | 原例行 | **已过，跳过** |
| 2026-11-10 09:00 前 F23 新鲜度 D1，20 次 | 11-09 18:00 截止 | `f23_freshness` | **未跑，0 次，过窗不补** |
| 2026-11-10 15:40 后 F21 d，5 次 | 11-10 00:40 起；实跑 02:25 / 17:25 北京 | `f21_trading_window` | **已完成 5/10** |
| 2026-11-11 开盘前 F21 d+1，5 次（任务单写 08:20） | 11-10 17:20 | `f21_trading_window` | 待跑（须新授权）；截止时刻文件只写「开盘前」，08:20 来自任务单 |
| 2026-11-11/12/13/16 09:00 前 F23 新鲜度，各 20 次 | 前一日 18:00 截止 | `f23_freshness` | 待跑；合计至多 80，加上已跳过的 20，不超过 CAPS 100 |
| 第 6 天后 F23 完整性 10 次 | 待编排者派单 | `f23_completeness` | 未跑；清单待确认 |
| 历史段 F35/F36 4 + F49 2 | 无交易日窗 | `history_actions` / `history_suspension` | 0 次；官方公告证据门禁未过，未补齐不得发历史请求（仓库内 T-B86 报告） |
| F14/F15 每个交易日 18:00 | 当日 03:00 MST | T-A22 列表 | 未实采；是否占用本批 128 **未查到明文**，待编排者 / 用户决定 |

T-B59 定向补证 7 次（见 §2.4）**不在** T-A19 128 次表内，不要擅自算进本批剩余。

剩余额度（仅就已查到的 T-B86 账本）：128 − 5 = **123**；其中 CAPS 仍可用的大致为 F21 5 + 新鲜度至多 80（另 20 过窗作废）+ 完整性 10 + 历史 6 + 预留 2。预留 2 不挪用。

### 2.3 交接入库：计数与结果摘要

| 文件 | 内容 | 谁提交、在哪条分支 |
|---|---|---|
| `docs/handover/data-validation/t-b86-ledger-summary.json` | 起始快照：total/halted/records 标识与 CAPS，无行情无证书 | **本单**已在 `docs/T-A110` 提交。合入 main / 交给 `team-b` 后作为起点 |
| `docs/handover/data-validation/segments/<segment_id>.json` | 每段 started/done（§3.5） | **新团队**在 `tb-*` 分支逐段提交，再合入 `team-b` |
| 更新后的 `t-b86-ledger-summary.json` | 每段结束后刷新 total、records 标识、摘要哈希；仍不含原始行情和证书 | 同上，由新团队提交 |

原始响应只允许留在仓库外 / gitignored 目录（沿用 `src/backend/probes/results/` 本地约定）。研究员核对用的脱敏 fetch JSON（协议 :35：每股 `security_code, fetched_at_beijing, fetch_ok, items:[{zt,t,nr}]`，无证书值）可按协议进入 `docs/strategies/T-R26/evidence/`——那是策略目录，**本单不改**；由策略研究员在其分支入库。

### 2.4 T-B59 补证（与 128 次批次分开）

依据 `/workspace/team/reports/T-B59.md`（提交 `7c0548a`，已在 `e44311a`；实现已合，补证未跑）：

- 已做离线口径与合成/回放测试；**真实 2024 日历端到端未关闭**；V5g/V5h 未宣告关闭。
- **定向补证最少 2 次**（须在用户电脑、用户授权后）：`GET /tcalendar/list/2024`；`GET /hsstock/financial/balance/<任务单所列证券>`（全历史、无日期参数）。具体证券与字段以该报告为准，本文不抄样本细节。
- 若同时补齐 T-R13 V5h，再加 5 次（income ×4 + cashflow ×1），**合计 7 次**。接口前缀 `/hsstock/financial/`。
- 研究员还须补名单核实等非调用项（报告末段）；缺这些也不能宣布关闭。
- 未查到这 7 次已被授权或已执行的记录。算在 §4 用户决定项。

## 3. 在用户 Windows 电脑上的运行办法

### 3.1 环境：WSL，不要 Git Bash

- 代码与 compose 入口：`docs/runbook/windows-local.md` :6–16、:41–54。部署脚本是 bash，须在 **WSL Ubuntu** 的仓库根执行，建议工作树放在 WSL 文件系统（不必只用 `F:\` 挂载路径）。
- `deploy/scripts/compose.sh` :31–40：**拒绝** Git Bash / MSYS / Cygwin / `Windows_NT`（exit 2），因为 `$HOME` 会指到 Windows 用户目录，密钥目录与运行栈不一致。T-A107 已核对这一点。
- 默认 `MAIRUI_MODE=replay`（`docs/handover/local-operations.md` :16）。切 live / 真实出网不是普通启动选项，须另获审批。VPN 掉线时先停，不要在不确定出口的情况下重试。

### 3.2 证书：只用约定名称，不落盘、不打印

正式路径是「用户在设置页录入、加密入库，ingest 用封装密钥解封」，**不是**把证书写进 `.env` 或临时文件。

| 名称 | 用途（只写名称） | 如何进入 WSL / compose |
|---|---|---|
| 每用户数据证书（库内，无全站环境变量名） | 实调身份；在本人设置页受控录入 | 不通过环境变量注入；见 `private-prerequisites.md` :14 |
| `data_licence_seal_private_keys` / `data_licence_seal_public_keys` | HPKE 封装/解封；私钥仅 ingest | 仓库外 `$AIA_SECRETS_DIR/`（`windows-local.md` :19–37）。`compose.sh` 以 **Docker secret** 挂载（`deploy/compose/docker-compose.yml` :533–540）：私钥只挂 ingest，公钥给 API/ingest |
| `AIA_SECRETS_DIR` | 密钥**目录路径**，不是证书值 | 写在仓库外 `deploy/env/.env`（权限 600）；示例键名见 `deploy/env/.env.example` |
| `MAIRUI_LICENCE` | **已废弃**全站变量；服务启动若发现非空应拒绝 | **不要**补进部署 `.env`，不要在 Windows 续跑里使用（`private-prerequisites.md` :16） |
| `MAIRUI_MODE` / `MAIRUI_REPLAY_DIR` / `MAIRUI_EGRESS_IP_EXPECTED` | 回放/真实模式与出口约束，不是证书 | 未审批保持 replay / 闭锁（:15） |

禁止：把证书值写入仓库、聊天、报告、段标记、日志；禁止打印；禁止把 T-B86 历史探针「环境仅允许 `MAIRUI_LICENCE` + umask 077 临时 `.tmp`」当作 Windows 常规做法（那是共享电脑探针的一次性安排，且续跑须走 §3.3 唯一出口）。共享电脑上的 `mairui-T-B86.tmp` 已在 F21-D 的 finally 删除，不要在 Windows 重建同名落盘文件。

### 3.3 出口只走 `egress.mairui_get`；STOP / 103 / 429 立即停

- 生产/续跑请求必须经 `src/backend/app/ingest/egress.py` 的 `mairui_get`（:448 起），并持有 `single_egress` 租约（:200–204）。契约顺序见 `docs/api-contract.md` 约 :1409：STOP/HALT → 租约 → 准入 → 再判 STOP/HALT → 窗口内 transport（不重试、不跟随跳转）→ 限流则写 HALT。
- 运行时 netguard（`src/backend/app/ingest/netguard.py`）拦截窗口外的麦蕊 DNS/连接；阻止事件打到 logger `app.ingest.netguard`，这不是额度账本。
- **STOP / HTTP 103 / HTTP 429 / 业务码 103 或 429**：立即停止，不重试、不改头、不换域、不换代理。写出 `halted` 与熔断原因。egress 在限流时写 HALT 文件（`HALT_LIMIT`，:54、:519–520）。**解除 HALT 或恢复出网必须用户本人确认**（`wrapup-deploy.md` :105、:201），编排者不能代为确认。
- T-B86-F21-D 那 5 次是在**共享电脑默认通道**发出，报告写明未切到本出口。它们已计入文件账本，但**不会**出现在用户 Windows 实例的 `ops.data_licence_events` 里。不要在 Windows 上重放这 5 个 id；也不要把「审计里没有这 5 条」当成没调用过。

### 3.4 计数以出口审计为准

权威顺序：

1. **用户 Windows 已部署实例**库表 `ops.data_licence_events`（契约 :1409、:1468；`actor=ingest` 等事件）。只抄事件类型、时间、次数、是否限流，不抄证书值、股东代码或原始响应。
2. HALT 文件是否存在、内容是否为限流类标志（只记种类，不把文件内容贴进仓库）。
3. 文件账本（§2.1）只作对照。脚本自报次数与审计不一致时，**以审计为准**，停止并交编排者对账，禁止改小 total、禁止重置账本（`tb86_offline.py` 文首 :9–10：缺失/未知状态 fail-closed，由编排者对账，不得清零）。

把 5 次共享电脑调用迁到 Windows 账本时：以本单 JSON 快照为起点写入 total=5，不在 Windows 审计里找这 5 条。

### 3.5 掉线后的幂等段标记（须新团队实现的契约，本单不写代码）

仓库里**没有** started/done + 摘要哈希的段标记实现。`tb86_offline.py` 的唯一 id + 先记账不能替代下面的契约。新团队实现时只许新增仓库外工具或后续另行派单的代码；本交接文档即契约正文。

- **段 ID** = `{键}-{窗口日期}-{段序}`。键用短名：`F21` / `F23-fresh` / `F23-comp` / `F14F15` / `F35F36` / `F49` / `TB59`。窗口日期用计划取数日的北京日历日 `YYYY-MM-DD`（无窗口的历史段用 `hist`）。段序两位，从 `01` 起。例：`F21-2026-11-11-01`、`F23-fresh-2026-11-11-01`。
- **文件**：`docs/handover/data-validation/segments/<段ID>.json`（UTF-8）。字段至少：`segment_id`、`key`、`window_date`、`seq`、`status`（`started` | `done` | `done_partial` | `failed` | `skipped_window` | `abandoned`）、`planned_calls`、`started_at`（America/Denver 带偏移）、`ended_at`、`calls_script`、`calls_egress_audit`、`official_count`（采用审计值；审计不可用则为空并 fail-closed）、`summary_sha256`（对脱敏摘要 canonical JSON 做 SHA-256；摘要只含代码列表、日期、HTTP 状态、条数、是否熔断，**不含**行情字段值与证书）、`notes`。
- **开始前**：若同 ID 已是 `done` / `skipped_window`，不得再发。否则先写 `status=started` 并提交或至少 fsync 落到磁盘后，才允许发出该段第一条请求。
- **正常结束**：按审计填写 `calls_egress_audit` 与 `official_count`，写入 `done`（或熔断时 `done_partial` / `failed`）和 `summary_sha256`，并更新 `t-b86-ledger-summary.json`。
- **只有 started、没有 done**（VPN 掉线、进程被杀、会话中断）：
  1. 不得用同一段 ID 再开跑，也不得换一个新 ID 把同一批请求再发一遍。
  2. 在用户实例只读查询 `ops.data_licence_events`（及 HALT）。能对应到本段请求的次数 = 已消耗额度。
  3. 审计显示已发出 N≥1：视为已消耗；补写 `done_partial` 或 `failed`，`official_count=N`，**不得重发已发出的请求**。未完成的标的是否另开新 `seq`，由编排者决定，且仍受 CAPS 与「过窗不补」约束。
  4. 审计显示 0 次：不得假定「额度未用」。保持 `started`，交编排者对账后才能标 `abandoned` 并以新 `seq` 重开（若窗口已过则标 `skipped_window`，不重开）。
  5. 审计不可用（库不可达、VPN 仍断）：fail-closed，停止，不猜测、不重试、不改 total。
- 过窗未跑的段直接写 `skipped_window`、`official_count=0`，例如 `F23-fresh-2026-11-10-01`。

## 4. 须用户本人决定的事项

新团队不得自行推定下列任一事项。由编排者向用户本人提问并留证：

1. **是否重新授权麦蕊调用**（交接后必须重新授权；当前新团队被要求不调麦蕊）。写明覆盖哪些段（F21 d+1、F23 剩余新鲜度、F23 完整性、F14/F15 18:00 列表、历史段、T-B59）。
2. **次数上限**：是否沿用本批剩余 123（其中过窗 20 不作他用、预留 2 不挪用），还是另给新上限。
3. **T-B59 的 7 次**（最少 2 次，含 V5h 则为 7 次）是否授权、是否计入或独立于第 2 项上限。
4. **是否把 G7 代批扩到 H-01 / S-01 以外**（现行书面授权只覆盖这两张卡，见 §5 所引 T-A109）。
5. **是否解除 HALT / 恢复出网**（若实例上已有停机标志或出口闭锁）。不在 2026-11-08 推送/本机部署长期授权范围内。

另外须编排者经私密渠道处理、不必写进仓库：把 F21 d 日脱敏快照交给新团队，供 d+1 对比。

## 5. G2 通过后：G7 代批与 draft→simulating

G2 本身通过，并不等于可以代批或晋级。权威条款与步骤在：

**`docs/reviews/T-A109-g7-delegation.md`**（本地 `docs/T-A109=ffddab6b3e6e8cc6745946f006a6929532b20f36`，随 T-A109 合入 main 后直接读该路径）。plan 2.5.13、契约 T-A18/T-A20、`docs/handover/roles-rules.md` 的同步正文也在那次提交里。

本文**不重写**其条款，只提醒接续时必须遵守的要点（详见该文 §1–§6）：

- 书面授权当前只覆盖 **H-01、S-01**；每次代批须引用覆盖该卡的用户本人授权。
- 不放松 G1–G6，不放松「缺证据不得批」。T-R41 仍缺项未齐（该文 §5）前不得代批。
- 2026-11-09 13:12:55（America/Denver）那次代批**不能**作为晋级依据。
- 正式 `draft→simulating` 在**用户 Windows 已部署实例**执行（`docs/handover/local-operations.md`、T-O35）；共享电脑 dev 库不得冒充已晋级。步骤、留证与回滚见该文 §6（编排者以管理员可信会话执行；须重输密码；脚本不得代填）。

## 6. 未查到 / 待补（不要编造）

- 架构师对 `watchlist20.yaml`、编排者对 `completeness_list.yaml` 的书面确认。
- F14/F15 每个「18:00 取 1 次」对应几次 HTTP（三个列表路径如何计数）；是否占用 T-B86 的 128 次。
- F21 d+1 窗口的硬截止时刻（任务单写 08:20，T-A19 只写「开盘前」）。
- F21-D 原始快照是否已通过私密渠道送达新团队。
- `check_f21_ready.py` 在任何实库上的输出。
- T-R26 台账/真值文件（目录在 `e44311a` 尚不存在）。
- T-B59 7 次是否已授权或已执行。
- 13:12 代批发生在哪套环境、库内审核是否已 lifecycle（T-A109 列为未决）。
- 用户是否把 G7 代办升为长期、是否覆盖其他卡。

## 7. 建议的续跑顺序（均须先有 §4 授权）

1. 接收 F21 d 日私密快照；在窗口内完成 F21 d+1；对比定稿与单位；更新段标记与摘要。
2. 在尚未过窗的北京 09:00 前完成剩余 F23 新鲜度天（过窗跳过）；研究员做真值与 `daily_check.py`（`PYTHONUTF8=1`）。
3. 清单确认后做完整性 10 次；出 T-R26 结论，交架构师裁是否升 verified_live。
4. F14/F15：授权后在交易日 18:00 实采，研究员做同日网页核对。
5. 历史段仅在官方公告证据补齐后进行；T-B59 按用户是否授权 7 次另排。
6. G2 相关键达到各自验收后，再按 T-A109 走代批与晋级，不要跳步。
