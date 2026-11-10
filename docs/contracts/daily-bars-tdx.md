# 通达信本地日线融合契约（T-A142，draft）

状态：draft，架构契约，不代表已实现。基线 main `ef32153`。依据：用户提议（编排者转述，见 `reports/T-A142.md`）与 `reports/T-A136.md` 方案 B 的格式调研。与 `daily-bars-source.md`（下称「源契约」）§8–§9 配套。

## 1. 定位：麦蕊为主

- 日报、today、owned 快照、17:15 每日增量**只用麦蕊**。通达信行不进这些链路。
- 通达信只做三件事：
  1. **交叉核对**：与已有麦蕊行逐字段比对，差异另行记录，不改任何一条原记录；
  2. **3 年以前的历史**：只供策略复测；
  3. **兜底**：麦蕊回填被拒（103、429、退市股 503 之类）的代码与日期，用通达信补，仍只供研究，不进日报链路。
- 导入是离线 CLI，不出网，不读证书，不需要单 D。

## 2. 存储口径

- 写入 `market.daily_bars`，只经 `upsert_daily_bars`：source 为 `tdx_local`，adj_type 为 none（只存不复权），source_licence_id 为空，is_suspended 为空，pre_close 为空（.day 的保留字段偶尔是前收，不可靠，不用）。
- 一条记录只来自一个源，不混写。主键 (code, trade_date, adj_type) 不改。
- 同键冲突：
  - 已有任何行（mairui、tdx_local、fake）时，通达信导入一律 DO NOTHING；同键不同值计入 `daily_bar_conflict` 统计与核对报告，不覆盖。
  - 已有 `tdx_local` 行、麦蕊后到：见 §7 U-T1。保守默认是麦蕊写入同样 DO NOTHING，于是该键保留通达信行；为保证「日报只用麦蕊」，快照侧按 §4 排除 `tdx_local`，并且源契约 §9.2 的 `backfill_ready` 不把 `tdx_local` 行算作已就绪。
- 复权按麦蕊口径：库里只存不复权；复权因子按麦蕊口径由前收（pc）推出。通达信没有可靠前收，所以只有通达信行的区间推不出因子，按 Q2 保守规则记 `adjust_factor_missing`，不补 1。
- 单位：
  - 价格：股票为整数 ÷100，到分；基金、债 ÷1000 的品种不导入（§3 只留 stock）；
  - 成交量：.day 个股为股，契约统一为股，直接写入（麦蕊侧 ×100 的规则不变）；
  - 成交额：float32，约 7 位有效数字，原值写入，核对时用容差（§5）。
- 停牌：.day 在停牌日一般没有记录。导入**不得**据缺行推断停牌，不写占位行；缺的日期保持缺失。

## 3. 导入 CLI

- 命令：`daily-bars-import-tdx`（`app/cli` 下新模块），默认 dry-run，`--apply` 才写库。
- 参数（不写死，等用户提供）：
  - `--dir`：通达信 vipdoc 目录（含 sh、sz、bj 下的 lday）；必填，不设默认值；
  - `--until`：截止日期，必填；须早于今天，且不晚于前一开市日（今天的 bar 交给 17:15 麦蕊批）；
  - `--from`：起始日期，可选；
  - `--scope`：owned（默认，只导 `daily_universe` 里的代码）或 market（受源契约 §9.6 的 `RESEARCH_MARKET_SCOPE_ENABLED` 把关）。
- 过滤：文件名经 `trades.normalize_code` 规范化为系统代码；只保留 market 主数据里 `securities` 的 type 为 stock 且 listing_status 为 listed 的代码，其余跳过并计数（约 4,000 个非 A 股品种）。规范化失败的文件计数后跳过。
- 解析：每条 32 字节，小端 `<IIIIIfII`；日期非法、高低价矛盾、价格为 0 的记录拒绝并计数。
- 单位自检（逐文件）：抽该文件全部记录，算成交额 ÷ 成交量，须落在当日 [low, high] 内（容差 1%）；不满足的比例超过 5% 时整文件拒绝，记 `tdx_unit_suspect:<code>`。
- 写入：按 `UPSERT_BATCH_ROWS` 分批；每次 `--apply` 写一条 pipeline_runs（stats 含文件数、导入行数、跳过数、冲突数、拒绝数与原因计数），不写路径原文以外的任何用户信息。
- 不出网：模块不得 import 任何 egress 或 transport；用例以 `egress.mairui_get` 调用数为 0 证明。
- Windows：路径用 pathlib 解析，不依赖大小写；日期按 Asia/Shanghai 判定今天。

## 4. 下游边界

- `daily_snapshot._load_bars` 增加条件：source 不是 `tdx_local`（NULL 与 mairui 照旧）。因此 owned 快照、analyze、日报、today 都看不到通达信行，`OWNED_VERSION` 不变。
- 研究读取入口本单不定，另开单；它可以读 `tdx_local`，但须在结果里保留 source。

## 5. 交叉核对

- 命令：`daily-bars-crosscheck-tdx`，参数同 `--dir`、`--from`、`--until`、`--scope`；只读，不写 daily_bars。
- 对象：同一代码同一日期，麦蕊行（source 为 mairui）与 .day 记录。
- 比对规则：
  - open、high、low、close：到分完全相等；
  - volume：完全相等（两侧均为股）；
  - amount：|差| ≤ max(1 元, |麦蕊值| × 2.4e-7)（float32 相对精度的 2 倍；1e9 量级约 ±240 元，覆盖 T-A136 的 ±64 元估计）；
  - 只在一侧有：单列为 missing_in_mairui 或 missing_in_tdx，不视为差异。
- 报告格式：写到 `--out` 指定的文件（JSON Lines，每行一项）：code、trade_date、field、mairui_value、tdx_value、tolerance、kind（mismatch、missing_in_mairui、missing_in_tdx）；末行为汇总（比对键数、各 kind 计数、超差率）。同时写一条 pipeline_runs 汇总，不写明细。
- 「另行记录、不覆盖」：核对结果只进报告文件与运行汇总，不改 daily_bars 任何行。

## 6. 迁移

- 新迁移 0033（单头由 0032 变为 0033）：把 `ck_daily_bars_source_allowed` 改为 source 为 NULL 或属于 fake、mairui、tdx_local。不改已有行，不加列。
- downgrade：存在 source 为 tdx_local 的行时拒绝；否则恢复 0032 的约束。

## 7. 待用户提供 / 确认

| # | 内容 | 保守默认 |
| --- | --- | --- |
| U-T0 | 通达信目录路径、截止日期 | 不导入 |
| U-T1 | 同一键已有通达信行、麦蕊后到时，是否让麦蕊替换。用户说「以麦蕊为准」，但主键一键一行，DO NOTHING 会让先到的通达信行留下 | 麦蕊也 DO NOTHING，快照排除 `tdx_local`，日报不受影响；需要替换时另开单（替换前先写核对报告） |
| U-T2 | 「兜底」补的行是否允许进入日报的历史窗口 | 不允许，只供研究 |

## 8. 验收（G/W/T）

开发时点：§3–§6 全部现在就能做（离线、不出网）；§5 与真实麦蕊行的比对要等单 D 之后库里有麦蕊行。

后端（新单 T1：迁移与导入）：
- `test_migration_0033_allows_tdx_local`（新，迁移测试）：Given 升到 0033 / Then 写 source 为 tdx_local 的行成功，写其他未知值失败；有 tdx_local 行时 downgrade 拒绝。
- `test_tdx_parse_record_layout`（新，不连库）：Given 一条构造的 32 字节记录（虚构代码 000001.SZ）/ Then 日期、OHLC ÷100、成交额 float32、成交量正确。
- `test_tdx_import_filters_stock_listed_only`（新）：Given 目录里有股票、基金、指数、已退市股票各一 / Then 只导入 listed 的股票，其余计入跳过数。
- `test_tdx_import_do_nothing_on_existing`（新）：Given 同键已有 mairui 行且值不同 / When `--apply` / Then 原行不变，冲突数为 1。
- `test_tdx_import_no_suspended_inference`（新）：Given 文件缺某开市日 / Then 该日没有任何行，is_suspended 不被写。
- `test_tdx_import_unit_selfcheck_rejects_file`（新）：Given 成交量按手写入的构造文件 / Then 整文件拒绝，记 `tdx_unit_suspect:<code>`。
- `test_tdx_import_until_must_be_past_open_day`（新）：Given `--until` 为今天、未来、休市日 / Then 拒绝；dry-run 默认不写库。
- `test_tdx_import_no_network`（新）：Given 打桩 `egress.mairui_get` / Then 调用数为 0。
- `test_snapshot_excludes_tdx_local`（新，连库，测试隔离库）：Given 某持仓代码在窗口内只有 tdx_local 行 / When build / Then 快照里该代码没有这些 bar，按既有规则记缺口。
- `test_backfill_ready_ignores_tdx_local`（新）：Given 窗口内全是 tdx_local 行 / Then `backfill_ready` 为 False。

后端（新单 T2：核对）：
- `test_crosscheck_tolerance_amount_float32`（新）：Given amount 差 200 元、量级 1e9 / Then 不算 mismatch；差 300 元 / Then mismatch。
- `test_crosscheck_report_jsonl_shape`（新）：Then 每行字段恰为 §5 所列，末行为汇总。
- `test_crosscheck_read_only`（新）：Then daily_bars 行数与内容核对前后相同。
