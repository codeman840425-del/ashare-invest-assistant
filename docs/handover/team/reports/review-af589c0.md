# 评审：af589c0（T-R12/T-R12a/T-R12b p13 财务时点探针：p13_fin_pit.py、p13_analyze.py、selfchecks/tr12_fin.py，以及 run_all/dryrun_mock/README 改动）

- 评审人：项目架构师
- 时间：2026-11-01 20:30 MST（America/Denver）
- 方法：
  - 在 /tmp 的干净导出（git archive af589c0）里跑，探针用单独的 venv（只装了 requests）。
  - 全程 `env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY`，并去掉代理变量；没有调用麦蕊。
  - 只评审，没有改仓库，没有推送。
- 判据：
  - plan 2.12.1；
  - T-R12e 补充裁定 V5i/V5g/V5j（2ac8e55，main 上对应 fdd7fdd，晚于本提交）；
  - /workspace/team/reports/T-R12-material.md §0。

## 结论

**代码可以推送（0 B）。但 T-B05 麦蕊实测前必须先修 M1，否则 V5j 要再开一次窗口。**
- 调用次数和点名运行这两项都符合要求，证书也不会落盘。
- 采集到的数据能覆盖 V5i 和 V5g，但离线分析还没输出 T-R12e 需要的判定（M2、M3）。这部分可以在窗口之后对原始文件离线补。
- V5j 需要 CDR 的 `zgb`，本探针完全没有采集（M1）。

## 实测

| 项 | 结果 |
|---|---|
| `run_all.py --dry-run`（本地伪造服务端） | **142 PASS**，“全部通过”，rc=0（与提交说明一致）<br>其中阶段 6 p13 有 50 条 PASS，包括：<br>· 缺省跑和 `--p13-restated` 跑都是“客户端 28 次 = 服务端增量”；<br>· manifest 的 sha256 一致；<br>· ①–⑨ 都有调用；<br>· 离线重算结果与原结果一致；<br>· “输出不含证书” |
| dry-run 日志逐条请求 | 28 行，URL 里的证书都显示为 `***`<br>gg 节点动态选到 sw_yx 和 sw2_490200 |
| `env -u MAIRUI_LICENCE selfchecks/tr12_fin.py <dryrun-p13 目录>` | **41 passed / 0 failed / 0 skipped**<br>离线回放重算结果等于 p13_analysis.json |
| `env -u MAIRUI_LICENCE p13_analyze.py <dryrun-p13 目录> --stdout` | rc=0，没有出网 |
| `select()` 点名测试 | `[]` → 不含 p13（12 个模块）；`p13`、`p13_fin_pit` → 只有 p13<br>`p11` → 不含 p13<br>**`p1` → 含 p13（4 个模块）；`p` → 含 p13（13 个模块）**（见 m1） |
| 后端 ruff check、ruff format --check、mypy --strict | 全部通过（probes/ 不在门禁内，按 pyproject 的设计） |

## 核对

| 检查点 | 结论 | 依据 |
|---|---|---|
| 调用次数 ≤ 28 | ✅ 计划合计 28 次：6+6+1+4+1+2(zg)+2(gg)+3+2+1。<br>⑤ gg 最多 2 次，`pick_gg_nodes` 最多返回 bank、insurance 两个节点；list 里找不到节点时少调。<br>不重试（`max_retries=0`），串行。 | p13_fin_pit.py:53–87；common.py:120 |
| 只在点名时运行 | ✅ 放在 `OPT_IN`，不进缺省的 ORDER；dry-run 里有对应断言。 | run_all.py `OPT_IN`/`select()` |
| 证书不会落入原始响应 | ✅<br>· `write_raw` 写盘前调用 `assert_no_licence`；<br>· manifest 里只存脱敏 URL，error 只取 text[:300]，而且同样经过 `write_raw`；<br>· dry-run 扫描整个运行目录，命中 0 次。 | common.py:373–376；p13_fin_pit.py:99–113；run_all.py `_scan_dir_for_licence` |
| 原始响应完整，可离线重算 | ✅ 每次调用保存完整的 raw_<key>.json，同一 jzrq 的所有 plrq 版本都保留；manifest 记录 sha256 和 fetched_at(UTC)。 | p13_fin_pit.py:16–21 |
| **V5i**：capital 的 plrq/bdrq 是否为回填值 | **数据够，分析缺**。<br>· 已采集 600519、000001、601318、000550 的 capital 全历史，以及前三只的 balance、cashflow 全历史（报告真实的 plrq 就在这些表里）。<br>· `capital_semantics` 只统计了 plrq=bdrq 的个数和 **bdrq** 落在季末的比例。<br>· 没有统计 **plrq 恰好是季末日** 的行。<br>· 没有把“bdrq 为季末的 capital 行的 plrq”和同一 jzrq 财报的 plrq（真实披露日）逐行比较。<br>· first_seen 目前只有 manifest 里每次调用的 fetched_at；分析结果里没有逐行带出。 | p13_analyze.py:320–335、612 |
| **V5g**：A+H、A+B 样例对照 zgb | ✅ 基本满足。<br>· 601318（as_of 2025-09-03）和 000550 都拿 `zgb` 与公开的总股本、A 股数比较，判定 includes_non_a、a_share_only 或 neither。<br>· 000550 的核对值出自 static.cninfo.com.cn。<br>· **601318 的核对值出自 pingan.cn，不是裁定要求的巨潮**（m2）。 | p13_analyze.py:27–31、357–373、615–617；T-R12-material.md:98–99 |
| **V5j**：CDR 样例的 zgb | ❌ **没有采集**。<br>· ⑨ 只调了 `financial/balance/689009.SH`，用来查币种和单位；<br>· 没有 `financial/capital/689009.SH`，也没有 689009 的日线；<br>· EXPECT 里也没有 689009 的基础股数或 CDR 份数核对值。 | p13_fin_pit.py:13、40、69–70；p13_analyze.py:27–31 |

## 问题

无 B。

- **M1（阻塞 T-B05 窗口）V5j 缺 CDR 的 zgb 数据。**
  - 位置：p13_fin_pit.py:40 `CAPITAL_CODES`、:69–70；p13_analyze.py:27–31、:612–617。
  - 要求，次数仍然不超过 28：
    1. 增加 `capital_689009`，用 ⑦ 的同一套逻辑。
    2. 为了不超过 28 次，建议去掉 `balance_600000`。银行资产负债已经由 000001 覆盖，600000 的 cashflow 保留。
    3. `EXPECT` 增加 689009 的核对值，来源用巨潮或上交所披露，注明日期：
       - 基础股票总数；
       - CDR 总份数；
       - 转换比例 10 CDR = 1 股。
    4. 分析输出 `v5j_cdr_unit`，取值 `zgb≈基础股数`、`zgb≈CDR份数` 或 `neither`。
    5. dry-run 的 mock 补上 689009 的 capital 响应，并断言 28 次和 ①–⑨ 齐全。
  - 是否另加 689009 日线，由后端评估：c × zgb 的量纲可以只靠 capital 判断，日线不是必需的。
- **M2（不阻塞窗口，但应在窗口前补上，避免回报时缺判定）V5i 的判定没有输出。**
  - 位置：p13_analyze.py:320–335、612。
  - 要求：在 `4_capital` 下为每只股票增加 `v5i_backfill`，内容如下：
    1. `plrq_is_quarter_end` 的行数和比例；
    2. 对每个 bdrq 为季末的行，取同一代码同一 jzrq 的 balance 或 cashflow 行，用各版本里最早的 plrq 比较，输出差值天数的分布和示例；
    3. 总判定：`backfilled`（capital 的 plrq 与财报真实 plrq 不一致，而且等于 bdrq 或季末）、`true_disclosure` 或 `inconclusive`；
    4. 每行带上 `first_seen_at`（等于该次调用的 manifest fetched_at），供以后快照比对。
  - 000550 没有财报，只做内部统计。
  - tr12_fin.py 增加对应的纯函数单测，正例和反例各一个。
- **M3（不阻塞窗口）分析里的 PB 时点口径还是 T-R12e 之前的。**
  - 位置：p13_analyze.py:442–450 `zgb_at`。
  - 现状：直接用 `plrq < d` 判断是否可见，没有实现 V5i 的 `max(next_trading_day(plrq), first_seen_at)`，也没有实现季末行按法定截止日保守处理（`basis.pit_basis=capital_deadline`）。
  - 风险：如果麦蕊确实回填，⑥ 的 PB 结果会带前视。
  - 要求：按 V5i 的规则加 `capital_deadline` 分支，或者在输出里明确标注 `pit_basis=pre_T-R12e`。
  - CDR 样例的 PB 不进入 ⑥ 时，在 `basis.verify_pending` 里加 `cdr_unit`。

- **m1**：`select()` 用前缀匹配，`run_all.py p1` 或 `run_all.py p` 也会把 p13 拉进来，多出 28 次调用。
  - 建议 OPT_IN 模块要求完整名或 `p13` 精确匹配。
- **m2**：601318 的核对值来源要补上巨潮链接，V5g 的关闭条件写明“对照巨潮”。
- **m3**：`VERIFY_PENDING` 里 601318 的 `non_a_share_capital` 是写死的。按 V5g 新口径应该来自配置名单，探针里注明“名单未接入，暂写死”即可。

## CI

| 项 | 状态 | 负责人 |
|---|---|---|
| backend ruff / mypy | 本地绿（probes/ 不在门禁内） | 后端 |
| secret-scan | 本提交没有新增指纹类内容；整体跟随 3e5e288..2954b6c 一起推送 | 运维 |

## 谁做什么

- **后端**：
  - T-B05 前修 M1 并重跑 dry-run，要求 28 次 = 服务端增量，并通过 tr12_fin。
  - M2、M3 最好也在窗口前做完；如果来不及，可以窗口后对原始文件离线补，原始响应完整保留。
  - 顺手处理 m1–m3。
- **架构师**：M1 修好后快速复核一次（只看次数、①–⑨ 和 V5j 输出），然后放行 T-B05。
- **测试、运维**：无。
