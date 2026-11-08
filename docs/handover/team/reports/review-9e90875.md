# 评审：af589c0 修复提交 9e90875（M1）· d2553ec（M2/M3/m1–m3）· 076ad51（T-R12g 跟进）

- 评审人：项目架构师
- 时间：2026-11-01 20:45 MST（America/Denver，UTC-7）
- 方法：用 `git archive` 分别导出三个提交到 /tmp 的干净目录，只读评审。dry-run 和 tr12_fin 都自己重跑，命令前缀 `env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY`，用 mock 服务端。全程没有调用麦蕊，没有改仓库，没有推送，也没有打印任何密钥。
- 依据：plan 2.12.1 的 T-R12e、T-R12f（38d7888）、T-R12g（9ad51b8）、T-R12h（7ec6fad，只是文档）；review-af589c0.md 的 M1–M3 和 m1–m3。

## 结论

三个提交都**可推**：0 B / 0 M，新提出 3 条 m，都不阻塞。
- af589c0 的 M1、M2、M3 已关闭，m1、m2、m3 也已关闭。
- **T-B05（p13 / T-R12 财务时点探针）可以放行**，用于真实点名运行（`run_all.py p13`）。真实运行后，V5i 和 V5j 的结论以产出的 `analysis.json` 为准，由人工签收。
- 推送顺序：这三个提交在 main 上和 e6ca937、f6c36ec、efb53b8 交错。这三个提交本轮不在我的评审范围内（是前端或运维提交）。它们能否连续推送，取决于第二阶段的总结论。

## 实测

| 项 | 9e90875 | d2553ec | 076ad51 |
|---|---|---|---|
| `run_all.py --dry-run` | rc=0，146 PASS / 0 FAIL，“全部通过” | rc=0，157 PASS / 0 FAIL | rc=0，**158 PASS / 0 FAIL**，“全部通过”（与后端自报一致） |
| p13 调用次数 | `client=28 server=+28` | 同左 | `[PASS] p13：未熔断且客户端 28 次 = 服务端增量 (client=28 server=+28)`；`manifest 28 条，sha256 一致、全部 200`；p13-restated 同样是 28/+28 |
| `selfchecks/tr12_fin.py` | 42 passed / 0 failed / 0 skipped | 50 / 0 / 0 | **51 / 0 / 0** |
| V5j 输出 | 689009 两个核对点都判为 zgb≈CDR份数 | 同左 | `fy2024_end zgb=717120523 → zgb≈CDR份数; fy2025_end zgb=720335578 → zgb≈CDR份数 → v5j_cdr_unit=zgb≈CDR份数` |
| V5i 输出（mock） | — | 5 码都有 verdict | 600519、000001、601318 为 backfilled，000550 为 inconclusive（no_report_rows），689009 为 backfilled |
| ruff | 不适用：pyproject 第 38 行起把 probes/ 排除在 lint 门禁之外，CI 的 ruff 和 mypy 都不覆盖 probes |

日志位置：/tmp/rv-1102/{9e,d2553ec,076ad51}_{dry,tr12}.log。按要求，这些日志会随 /tmp/rv-1102 一起清理。

## 核对

| 要求 | 结果 | 证据 |
|---|---|---|
| 调用次数仍为 28 | ✅ | CAPITAL_CODES 新增 689009.SH，用 `BALANCE_SKIP={"600000.SH"}` 抵消一次，合计 6+5+1+5+5+3+2+1=28。客户端计数、服务端增量和 manifest 三方一致。 |
| V5j：689009 的 capital 已采集 | ✅ | p13_fin_pit 采集 `capital_689009`；dryrun_mock 有对应行；run_all 检查已采集。 |
| V5j：预期值和出处 | ✅ | p13_analyze.py:38–46 的 `EXPECT["689009_cdr"]`：ratio 10（10 份 CDR = 1 股 B 类普通股）。<br>fy2024_end：717,120,523 份 / 71,712,052.3 股。<br>fy2025_end（not_before 2025-12-17）：720,335,578 份 / 72,033,557.8 股。<br>出处：巨潮 2026-03-31 九号公司 2025 年年度报告（static.cninfo.com.cn/finalpage/2026-03-31/1225063705.PDF）。<br>比例另引上交所上市公告（存托凭证）〔2020〕189 号（CDR_RATIO_SAMPLE），满足 T-R12f 第 7 条“招股书或上市公告”的要求。 |
| V5j 判定逻辑 | ✅ | `cdr_unit_check`（441–458）：两个核对点都要在窗口内，并且分别命中份数或基础股数，才下结论；否则判 neither，保留 verify_pending cdr_unit。自检覆盖了四种情况：两点都是份数、都是基础股数、两点不一致、只有一点。 |
| V5i 分析符合 T-R12f/g | ✅（附 m-a） | `v5i_backfill`（532–）给出三项：plrq 落在季末的占比；季末 bdrq 行与同期报告最早 plrq 的差天数分布；判定（backfilled / true_disclosure / inconclusive）。first_seen_at 取自 manifest 的 fetched_at（load_first_seen）。M2 关闭。 |
| T-R12f 第 1–3 条 | ✅ | `v5i_applies`（489）：bdrq 为季末，并且 plrq=bdrq 或 plrq 为季末。<br>`capital_deadline`（483）按 bdrq 所属报告期取截止日：Q1 4-30、H1 8-31、Q3 10-31、年报次年 4-30。<br>回填行的可见时间是 max(ntd(plrq), ntd(截止日)) 09:30，`pit_basis=["capital_deadline"]`，是数组。pb_at（707）把它复制成数组。mock 检查“PB pit_basis 为数组”PASS。 |
| T-R12g：截止日只套首次回填的季末行 | ✅（附 m-b） | `capital_visible(r, incremental_first_seen_at)`（494–518）：<br>传了 first_seen_at 的增量行取 max(ntd(plrq) 09:30, first_seen_at)，`pit_basis=[]`，rule=incremental_first_seen_at，不套截止日；<br>不传的（首次全量回填，探针的全历史拉取属于这一类）套截止日；<br>非 V5i 行取 ntd(plrq)。<br>有自检对比增量和回填两种情况。 |
| zgb_at 按新规则 | ✅ | `zgb_at`（609）只在 bdrq ≤ d 且 `capital_visible(r).visible_from ≤ d` 的行里取 bdrq 最大的一行，并携带 `_pit`。M3 关闭。<br>ntd 用“下一自然日”近似。对交易日 d 来说，`nxt(x) ≤ d` 和 `ntd(x) ≤ d` 等价，所以不会产生前视。 |
| T-R12f 第 4–8 条和 T-R12g 的 CDR 规则 | ✅ | share_class_check 取值为 unavailable 或 list（列名按 T-R12h 进 config）。<br>CDR 按 securities.type=cdr 识别，照常计算，verify_pending 加 cdr_unit。<br>zgb≈基础股数时 mcap 乘以 config 的比例，zgb≈CDR份数时不乘。<br>076ad51 删除了 S2 剔除字段，自检断言 basis 里没有 `exclude*`（1055–1058）。<br>银行和保险不排除。 |
| m1：opt-in 精确点名 | ✅ | run_all.py:46–49 只认完整名或编号，比如 `p13`，`p1` / `p` 前缀不会把它带上。 |
| m2：601318 出处 | ✅ | p13_analyze.py:30–33 改为巨潮 2026-03-27 中国平安 2025 年年度报告摘要（1225038326）。000550 同样来自巨潮。 |
| m3：non_a 从名单读取 | ✅ | 不再写死在 VERIFY_PENDING 里（p13_fin_pit.py:48 只剩银行和保险标记）。mock 检查“601318 non_a_share_capital 来自名单（m3）”PASS。 |
| README | ✅ | 补了回放说明和 T-R12g 的说明，与代码一致。 |
| aia_maint-grants.md §7:297 | ✅ | reports/aia_maint-grants.md 第 297 行补了一句：“aia_api 的 aia_deny 只放 licence 密文，不扩展（T-O11 裁定）”。与 reports/T-O11-aia_deny-ruling.md 一致。注意这个文件不在 git 里。 |

## 问题

**B：无。M：无。**

- **m-a（后端）** p13_analyze.py:550–556，`v5i_backfill` 把**所有**季末 bdrq 行都算进 diffs 和判定，包括 `v5i_applies=False` 的行（plrq 是真实日期，既不等于 bdrq，也不在季末）。mock 下 689009 的情况是：`plrq季末 n=0`，却因为一条非适用行（diff=-2）判成了 backfilled。偏差方向是保守的（倾向保留截止日规则），所以不会造成前视，但会让人工签收时误读。要求：判定只基于 `v5i_applies` 行；非适用行另列统计。
- **m-b（后端，T-B55 实现时必须注意）** p13_analyze.py:505–510，增量路径的 `visible_from = va.date()`。first_seen_at 如果晚于当日 09:30（比如 16:00 才采到），这一行会被当作“当日 09:30 起可见”，这与函数自己声明的语义不符。探针里的 zgb_at 不走增量路径，所以本次不受影响。要求：va 的时间晚于 09:30 时，visible_from 取下一交易日；或者落库实现时一律按 visible_at 比较。
- **m-c（后端）** docstring 把“下一自然日”称为“保守近似”。实际上对交易日来说它与 ntd 等价，用于非交易日则偏激进。建议改写措辞，避免 T-B55 照抄时直接用自然日。

## CI

probes/ 不在 ruff、mypy、pytest 的门禁范围内。三个提交都没有改 app/、tests/、frontend/ 或 CI 配置，所以对 backend、frontend 和 secret-boundary 三个 job 都没有新增影响。CI 状态按第二阶段的总评审报告。

## 谁做什么

| 角色 | 事项 |
|---|---|
| 后端 | 修 m-a、m-b、m-c，可以跟着下一次 p13 提交一起改。T-B05 放行后，按点名方式真实运行 p13，然后提交 analysis.json 和 manifest。 |
| 测试 | 无新增。 |
| 架构师（我） | 真实运行后签收 V5i 和 V5j 的结论。如果 V5j 确认是 zgb≈CDR份数，按 T-R12g 清除 689009 的 cdr_unit。 |
