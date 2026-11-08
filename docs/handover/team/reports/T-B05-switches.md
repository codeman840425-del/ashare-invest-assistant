# T-B05 准备：p11/p12 复测开关与规则收紧（后端）

- 日期：2026-11-01（MST）。提交：**f065f8d**（未推送）。基于 38c257f。
- 本次**没有调用麦蕊**，没有读取或打印 `MAIRUI_LICENCE`（所有命令都用 `env -u MAIRUI_LICENCE`）。`results/STOP` 没有改动（sha256 `02339d1e…7fbe17`，每次 dry-run 前后都核对过）。`tests/` 没有改动。
- 改动的文件（按路径提交）：`src/backend/probes/{p11_gaps,p12_code_lists,run_all,dryrun_mock,p11_replay}.py`、`probes/README.md`、`src/backend/selfchecks/{tb48_p11,tb05_switches}.py`（tb05_switches 是新文件）。
- 团队文档：本文件、`T-B05-recheck.md`（第 1、2、3、5 项的“未实现”改成用法和实测次数）、`status/后端.md`。

## 结果

| 项 | 结果 | 说明 |
|---|---|---|
| 1 精度差规则收紧 | **通过** | 见 §1 |
| 2 factor/batch 数据日期 | **通过** | 见 §2 |
| 3 复测开关 | **通过** | 见 §3 |
| 自检 | **通过** | `selfchecks/tb05_switches.py` 39/0/0；`tb48_p11.py` 46/0/0；`p11_gaps` selftest_pure 14 项全部通过 |
| dry-run | **通过** | 网络命名空间（`unshare -rn`）内跑缺省全流程，92 PASS / 0 FAIL，退出码 0，`blocked=[]` |
| 密钥扫描 | **通过** | `secret_scan.py files` 和 `range 38c257f..f065f8d` 都是 0 阻断、0 警告；gitleaks 扫这个提交：no leaks |

## 1. precision_only 收紧

新规则（`p11_gaps.precision_only`）。三个条件同时满足才算精度差：
1. 两个值的小数位数不同。
2. 较短一方的小数位数 k 满足 4 ≤ k ≤ 8。
3. 较长一方按 k 位做 ROUND_HALF_UP、ROUND_HALF_EVEN 或 ROUND_DOWN 之后，用 Decimal 精确比较，与较短一方相等。

自检用例：

| 用例 | 结果 |
|---|---|
| 1.<account>↔1.471418 | 算 |
| 82.98214819072565↔82.982148 | 算 |
| 2.12345678↔2.1235 | 算 |
| 15.0↔14.97（双向） | **不算**（反例） |
| 1.<account>↔1.471419 | 不算 |
| 较短一方不足 4 位（1.47、100.0↔99.99999） | 不算 |
| 小数位相同 | 不算 |

另外，15.0→14.97 发生在披露前时，计入真实跳变，判 `lookahead_suspected`（自检用例：from=15.0、to=14.97，变化日落在报告期末与 plrq 之间）。
凡报 `lookahead_suspected`，都列出触发它的每个 `before_disclosure` 变化点的 date、from、to（`classify_pit.details.before_disclosure`，脚本已带 from/to）；本次离线重放 run-20261101-190106 披露前跳变 0 个，没有 `lookahead_suspected`，故无 from/to 可列。

**离线重放**（`p11_replay.py --tag T-B05 results/run-20261101-190106`，生成 `p11_gaps.replay-T-B05.json`。该文件被 gitignore，旧的 T-B48 重放没有覆盖）：
- profit_yoy、roe_ttm 都是 `consistent_with_pit`。
- 披露后跳变 5 个，披露前 0 个，precision_only 各 2 个。
- batch_as_of=ok，equal=true。
- **§16 结论不变。** 实测的两个精度差都是 6 位截断，满足新规则，所以判定不变。

**附带改动**：`tb48_p11.py` 原来有一个用例 1.0↔1.0000001。它较短一方是 0 位小数，与 15.0↔14.97 同类，在新规则下按设计不再算精度差。我把它换成 1.234567↔1.2345671234（6 位截断）。这是规则收紧的预期结果，不是回归。

## 2. factor/batch 数据日期（plan 34d475d）

- `batch_dates` 取响应里的日期：记录层的 `trade_date`/`date`（包括 `factors` 内的）优先，没有时用响应层的 `data.trade_date`。
- `batch_asof(请求日, 记录日, 响应日)` 返回 `status`、`data_date`、`date_source`、`use_for_backfill`、`reason`。
- 以下三种情况都记 `as_of_mismatch`，`use_for_backfill=false`：
  - 记录日与响应日不同（`record_vs_response_differ`）
  - 都没有日期（`missing_data_date`）
  - 与请求日不同（`data_date_differs_from_request`）
- item67 的结论新增 `batch_as_of` 字段。as_of_mismatch 时 `history_vs_batch_same_day.*.equal=null`，不参与比对。
- 自检覆盖了上面各分支，并用 item67 集成：mock 在请求 2026-04-17 时返回 20260130，结果是 mismatch、equal=null、不回填。

**裁定前提有误**：裁定里写的“请求 20260417 → 返回 20260130”是 T-B48 重放造成的假象。重放用的是重建序列（只有跳变点）的中点，算出来是 2026-04-17。原 run 实际请求的是 20260130，返回的也是 20260130，两者一致。重放现在改为用原 run 记录的请求日（`PIT_BATCH_DAY`，输出 `batch_request_day`）。不修这一点，新的检查会在重放里报出一个假的 as_of_mismatch。

## 3. 复测开关（用法和次数见 probes/README §6A）

| 开关 | 预计次数 | dry-run（客户端 = 服务端增量） |
|---|---|---|
| `--p11-only gap1 --gap1-codes 5 只`，盘中 | 1 + 5×2×6 = 61/时段 | 61 ✓（独立 dry-run 43 PASS） |
| 同上，盘外 | 0 | 0 ✓ |
| `--p11-only gap6-history` | 2 | 2 ✓（38 PASS） |
| 同上，加 `--history-baseline`（无改写） | 2，比对是离线的 | 2，结果 `no_rewrite` ✓ |
| `--p11-only gap6-nulls` | 1 ztgc + 7 factor/all = 8 | 8 ✓（38 PASS） |
| 同上，加 `--zt-codes`（收盘后复跑） | 8 | 8 ✓ |
| `p12 --p12-only hslt` | 1 | 1 ✓（28 PASS） |
| `p11 p12 --p12-only hslt` | p12 为 0（复用 GAP4） | 0 ✓（48 PASS） |
| 不带开关 | p11 44 次（盘后 33），p12 5 次（全流程 2 次） | 不变 ✓ |
| 非法参数 | 退出码 2，0 次调用 | ✓ |

上面的矩阵也作为 dry-run 的阶段 5 自动执行（可用 `--skip-switch-matrix` 跳过）。每次运行都核对：结果里只有该开关对应的项、输出不含证书、跑完开关复原为缺省值。

研究员的两点要求：
- (a) GAP1 对每个源、每个 源×股票 都给出未修正和 NTP 修正后两套 p50/p95/max。`stale_threshold.ref_p95_s` = 各源修正后 p95 的最大值；没有 NTP 时退回未修正的 p95，并在 `basis` 里注明。
- (b) gap6-nulls 记录 `zt_sampled_at_bjt`，只从 `fbt` ≤ 取样时刻的股票里选，并把被拒的数量按原因计数。mock 里放了一只 fbt=23:59:59 的股票，自检确认它被拒绝。

## 未决问题

1. **w32tm 符号**：`/dataonly` 输出按“正值 = 本机比 NTP 快”读入，这一点没有在 Windows 上实测。结论里有 `ntp_sign_check`（和 HTTP Date 钟差比符号）。第一次跑时请人工看一眼，符号相反就用 `--local-ahead-s` 手工给值。
2. **stale_threshold 建议值**：公式 `ceil(max(2×参考 p95, 10 s))` 是后端拍的经验值，需要用户或研究员确认（T003-gaps-catalog 第 27 行）。
3. **batch 日期层级**：有记录层日期时以记录层为准；只有响应层 `data.trade_date` 时也接受（实测响应只在响应层带日期）。如果架构要求必须是记录层日期，改一行就行。
4. **gap6-history 基线**：原 run-20261101-190106 没有存完整序列，不能当基线。第一次 gap6-history（或第 4 项的 p11 复跑）就是基线，7 天后再比对。
5. **mock 边界**：mock 的 ztgc 有两只 fbt 是 00:00:01/02。如果 dry-run 恰好在北京时间 00:00:00–00:00:02 运行，选股数可能不足，只影响 dry-run，不影响真实运行。
6. **ruff**：两个 selfcheck 文件 `ruff check` 和 `ruff format --check` 都通过。probes 目录一直没有按项目的 ANN 等规则维护：HEAD 已有 319 条，本次之后 472 条，新增的主要是类型注解类。F/E9 级别没有新增问题。如果要把 probes 纳入 lint，建议另开任务。
