# T-R65：复测状态输入数据补齐（深市 ST / 沪市 ST / 上市状态 / 终止名单 / runner 接线）

> 依据：T-A154 三条件；任务 T-R65｜2026-11-11 北京时间｜维护：策略研究员
> 分支 `ds/T-R65`（基于 `ds/T-B136@d4405a8`，runner 实现所在分支）；数据本体放 `data/`（gitignored），仓库只入脚本/清单/说明。
> 红线：只读公开源 + 库内已有数据；零麦蕊；不写正式库；产物 sha256 入 manifest。

## 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| ① | 深市 ST 历史（深交所简称变更 → runner 输入） | **完成**（补 302 号段，见下） |
| ② | 已知子集三件套：沪市 ST、上市状态历史、沪深终止名单 | **完成**（P9 口径缺口待裁定） |
| ③ | runner 接线：三项输入 + coverage 非 null 预检 + 覆盖比例入 summary 首页 | **完成** |

## 产物清单（数据在 `data/retest-inputs/`，gitignored）

| 产物 | 行数 | sha256 | 说明 |
|---|---|---|---|
| `st_history_sz.csv` | 3,554 | `1b91cf2f…c371b` | 深市，3,021 只 |
| `st_history_sh.csv` | 2,654 | `e6b22041…653a3` | 沪市，2,396 只 |
| `st_history.csv` | 6,208 | `9500e791…c2154` | 合并，5,417 只（runner `--st-history`） |
| `listing_history.csv` | 5,627 | `6ea03f73…2b383` | 沪深上市状态（runner `--listing-history`） |
| `termination_list.csv` | 337 | `9f781837…f856d` | 沪深终止名单（runner `--delisting-list`；含 `no_period_evidence` 列） |
| `delisting_period.csv` | 106 | `cc838335…6bcd8` | 退市整理期起点（listing 构建输入 + 证据） |

完整 sha256 与统计：`manifests/*_manifest.json`。

## ① 深市 ST 历史 → runner 输入

- 来源：深交所「上市公司简称变更」xlsx（SSGSGMXX，全历史 1994-01-03 至 2026-11-10；sha256 `9291117a…`）。
- 口径：`is_st` 仅当简称以 `*ST` / `ST` 开头（NFKC、去空白）；「退」不计 is_st；不与 `security_risk_flag_history` 混写。
- 本轮修正：补 **302 号段**（中航成飞 302132，HF 池内），股票数 3,020 → 3,021、区间 3,553 → 3,554；sha 由 `869b9542…` 变为 `1b91cf2f…`。

## ② 沪市 ST / 上市状态 / 终止名单

### 沪市 ST 历史 `st_history_sh.csv`

- 来源：巨潮公告标题检索（9 类短语：撤销/实施/推行「退市」「其他」风险警示、被实施两类、进入退市整理期；窗口 2021-01-01~2026-11-10，两次抓取共 6,842 条，manifest 记每个响应 sha256）＋ 4 只已知缺口的逐股公告补漏（`--per-stock-jsonl`）。限流：单线程 1.0–1.2s/请求，0 失败。
- 判读：按 `暨/及/并/、/，/。` 分句；只撤销 → false；撤销其一但继续/新实施另一类 → true；只实施 → true；「继续实施/叠加/进展/申请撤销中」判「仍处于风险警示」断言；「可能被实施」先剔除。
- 日期：公告日后第一个交易日生效；保守外扩 1 个交易日（置 true 提前、置 false 延后）。窗口起点状态取窗口前最后一条事件（切换按其值、断言按 true）；窗口内出现「仍处于风险警示」断言而状态为 false → 保守补 ST 并逐条入 manifest。
- 覆盖：2,396 只（HF 池 2,383 + vipdoc-only 13），2,654 区间，225 只有 ST/*ST（242 段）。
- **校准（深市简称变更为真值，同日、同判读规则）**：over 2,888 股票日（0.09%）、under 790（0.025%）、窗口内启动段漏 2 只（000610、002102，均为 2026 年新增且公告未入索引）。
- **收盘状态核对（交易所 2026-11-06 快照）**：剔除 33 只「窗口结束后另有事件」的股票后，2,361 只中 0 不一致。
- 东财 F10 曾用名链：只做旁证。实测链不含当前简称、退市股返回 `--`，不能当权威；用它定位到 600198/600239/600807/688053 四只缺口，逐股公告补漏后修正。

### 上市状态历史 `listing_history.csv`

- 覆盖 5,417 只（= T-B136 正式跑股票池），5,627 区间；状态 `listed` / `delisting_period`(106) / `delisted`(106)。
- 起点 = max(2022-01-01, 上市日)；上市日后于窗口起点的 813 只，窗口前日期不覆盖（runner 记 `listing_status_unknown` 剔除并计数）。
- 退市整理期起点：深市简称「退」段 62 只（与巨潮首公告核对，日差 0 或 +1~2 天）+ 巨潮首次「进入退市整理期」公告 44 只；来源混合时以简称段为先。
- 86 只无整理期起点（多为交易类强制退市/主动退市）：`listed` 段截至终止日前 30 自然日，尾部不覆盖（`listing_status_unknown` 剔除并计数），逐只入 manifest `fallback_stocks`。

### 终止名单 `termination_list.csv` 与整理期 `delisting_period.csv`

- 337 行（SH 148 / SZ 189）。SZ 来自深交所终止上市导出（212 行，B 股 23 行不计、A 股 189 行）；SH 来自库内 `exchange_delist_list` 来源的 `delisted`+`delist_date`（148 行，含 2022 年前）。
- 窗口内（2022-01-04~2026-08-06）188 行，**全部带巨潮「终止上市」公告 URL**（188/188）；无整理期公告的行带 `no_period_evidence` 标题证据标签（窗口内 71 行 title_evidence / 12 行 no_title_evidence）。
- 交叉核对：深市 xlsx vs 库内日期 0 差异；窗口内名单与股票池 0 缺失（P9 `missing`=0）；整理期起点晚于最后一根 bar 的 0 只（P9 `truncated`=0）。
- 整理期起点 = 首次「进入退市整理期」公告日（早于实际首日，保守），106 只；公告日到终止日中位数 31 自然日。

### P9 退市整理期口径（T-A155 裁定落地）

- 判据：无 `delisting_period` 区间时，以 HF `coverage_by_instrument.csv` 的 `expected_end_date` 与最后一根 bar **判等**（不另设自然日阈值）；不等时只有缺口交易日全部为已确认停牌才按「停牌到摘牌」放行，否则走尾段缺失路径（fail）。
- 四分类（`summary.json` 的 `delisting` 节点逐股列出，窗口内 188 只全部命中）：
  - `pass_with_period` 105：整理期起点 ≤ 终止日且最后一根 bar ≥ 起点；
  - `no_delisting_period_by_rule` 69：无整理期，`expected_end_date` == 最后 bar，且终止上市公告标题有规则证据（交易类/面值/市值/主动退市等）；
  - `no_delisting_period_evidence_only` 12：同上判等通过，但公告标题无证据；另标 `residual_risk`，后续逐股读终止上市公告正文交叉核收口；
  - `suspended_until_delisting` 2（600355、000638）：停牌到摘牌，最后 bar 距终止日 >5 日但与 `expected_end_date` 相等。
- 模拟：`judgement._delisting` 对真实产物输出 `state=pass`、105+69+12+2=188、`period_unknown` / `tail_missing` / `missing` 全 0。
- 证据：`manifests/p9_no_delisting_period_evidence.json`（逐股标题关键词分类）；`termination_list.csv` 的 `no_period_evidence` 列承载 runner 侧标签。

## ③ runner 接线

- `runner_data.require_status_inputs`：`st_history` / `listing_history` / `delisting_list` 任一缺失 → `DataFormatError` 拒绝执行。
- `preflight`：`st_coverage` / `listing_coverage` / `termination_list` 任一为空 → 拒绝（T-A154，防「输入给了没吃」）。
- `StockCache.prepare` 累计按交易所按年计数，`summary.json` 首页新增 `coverage`：`by_exchange_year` / `by_exchange` 的 `st_known_share`、`listing_known_share`、`st_true_share`、`delisting_period_share`。
- 测试：`tests/backend/retest/test_status_inputs.py` 17 例（预检拒绝、load_status_history 契约、覆盖比例算术、P9 四分类与尾段缺失路径）；`tests/backend/retest` 全套 42 例通过。

## 自检

```bash
# 三件套结构 + P9 就绪度（只读 data/，不联网）
uv run --no-project python docs/strategies/T-R65/check_status_inputs.py \
  --st data/retest-inputs/st_history.csv --listing data/retest-inputs/listing_history.csv \
  --delisting data/retest-inputs/termination_list.csv \
  --hf-manifest data/hf-1min/2022plus/manifest_files.csv \
  --coverage-csv data/hf-1min/raw/metadata/coverage_by_instrument.csv \
  --securities-csv <securities 导出> \
  --calendar data/hf-1min/raw/metadata/market_calendar.csv
```

## 复现（抓取脚本，全部只读公开源）

```bash
# 关键词事件（2021 与 2022-2026 两段；沪市 ST 主来源）
uv run --no-project python docs/strategies/T-R65/fetch_cninfo_st_events.py --out <dir> --sdate 2022-01-01 --edate 2026-11-10
uv run --no-project python docs/strategies/T-R65/fetch_cninfo_st_events.py --out <dir> --sdate 2021-01-01 --edate 2021-12-31
# 逐股公告（终止名单 URL + 整理期起点；orgId 自动解析）
uv run --no-project python docs/strategies/T-R65/fetch_cninfo_per_stock.py --codes-file <终止名单窗口 CSV> --out <dir>
# 构建
uv run --no-project python docs/strategies/T-R65/build_termination_list.py --szse-xlsx <szse_delist.xlsx> --securities-csv <sec.csv> --per-stock-jsonl <per_stock.jsonl> --out-dir data/retest-inputs
uv run --no-project python docs/strategies/T-R65/build_listing_history.py --hf-manifest … --securities-csv … --name-history-csv … --coverage-csv … --delisting-period-csv … --vipdoc-sh … --vipdoc-sz … --out-dir data/retest-inputs
uv run --no-project python docs/strategies/T-R65/build_st_history_sh.py --events … --per-stock-jsonl … --hf-manifest … --vipdoc-dir … --calendar … --sz-csv … --securities-csv … --out-dir data/retest-inputs
```
