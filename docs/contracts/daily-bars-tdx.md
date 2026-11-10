# 通达信本地日线融合契约（T-A142，T-A143 修订，draft）

状态：draft，架构契约，不代表已实现。基线 main `ef32153`。依据：用户提议（编排者转述，见 `reports/T-A142.md`）与 `reports/T-A136.md` 方案 B 的格式调研；数据现状据编排者 2026-11-10 只读扫描（§1.1，未经架构核实）。与 `daily-bars-source.md`（下称「源契约」）§8–§9 配套。

## 1. 定位：麦蕊为主

- 日报、today、owned 快照、17:15 每日增量**只用麦蕊**。通达信行不进这些链路。
- 通达信只做三件事：
  1. **交叉核对**：与已有麦蕊行逐字段比对，差异另行记录，不改任何一条原记录；
  2. **麦蕊回填起点以前的历史**：实际只有约 2021-08 到麦蕊 3 年回填起点之间、约 2.3 年，只供策略复测；
  3. **兜底**：麦蕊回填被拒（103、429、退市股 503 之类）的代码与日期，用通达信补，仍只供研究，不进日报链路。本期只做到「核对 CLI 能列出这些代码与日期在通达信里有没有数据」；真要把兜底行写进重叠期，会与 §3.4 的截止规则冲突，按 §7 U-T2 的保守默认另开单，本期不写。
- 导入是离线 CLI，不出网，不读证书，不需要单 D。
- 与麦蕊 3 年回填的重叠期（约 3 年）**只做交叉核对，不写入**（§3.4）。

### 1.1 数据现状（据编排者 2026-11-10 只读扫描，架构未核实）

- 用户提供的目录是其 Windows 电脑上的 D:\西部证券\vipdoc（只作说明，代码与配置里不得出现此路径）。用户本人表示不清楚数据从何时开始。
- 日线 lday：sh 4,919、sz 4,437、bj 359 个 .day，全部覆盖 2021-08-02 至 2026-11-10，每只约 1,277 根，不复权。
- 其中 A 股约 5,600 只（sh 2,332、sz 2,917、bj 357）；其余为指数、基金/ETF、债券、板块（880/881）。ds 目录是扩展市场（港美期货等），与 A 股无关，不导入。
- 另有 1 分钟线 .lc1（约 133 个交易日）与 5 分钟线 .lc5（约 287 个交易日）。T-A143 起改为必需，见 `intraday-bars.md`。
- ~~用户电脑会离线：任何方案都不得依赖它在线。~~ T-A143：编排者 2026-11-10 裁定部署就在用户自己的电脑上，导入在部署运行时进行；用户电脑关机时部署本身也停，不另设在线要求。

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

## 3. 数据搬运与导入

### 3.1 原则（T-A143 取代 T-A142 的手动拷贝打包方案）

- 依据：编排者 2026-11-10 裁定（T-A143 派单）：部署就在用户自己的电脑上（docker compose）。
- 不拷贝、不打包、不经我们的 box、不经 egress。通达信目录以**只读**方式挂进容器，CLI 直接读。
- **挂载与导入都必须由用户本人同意，默认不导入**（§7 U-T0）。用户同意之前，运维单 O1 不执行，CLI 只能 dry-run。

### 3.2 只读挂载（运维单 O1）

- 挂载对象：vipdoc 下 sh、sz、bj 三个 lday 目录（日线）；分钟线的 minline、fzline 见 `intraday-bars.md` §1.2，同一张 O1 一起挂。不挂 ds 及其他目录。
- 方式：compose 里以只读卷（`:ro`）挂到后端容器内的一个根目录下，保持 sh/lday、sz/lday、bj/lday 的相对结构。
- 宿主路径作为部署参数由运维给出（例如写在部署机本地的 env 文件里），**不写进代码常量，也不写进 compose 的默认值**。用户给出的目录（§1.1 的 Windows 路径）只作为说明文字出现在本契约里。
- 容器内路径作为 CLI 参数传入。

### 3.3 导入 CLI

- 命令：`daily-bars-import-tdx`（`app/cli` 下新模块），默认 dry-run，`--apply` 才写库。
- 参数（都不写死）：
  - `--root`：容器内挂载根目录，必填；其下须有 sh/lday、sz/lday、bj/lday，缺任一即拒绝；
  - `--audit-dir`：容器内**可写**目录，必填，用于落盘 sha256 清单与核对结果；不得位于 `--root` 之下；
  - `--until`：截止日期 D，必填（§3.4）；
  - `--from`：起始日期，可选，缺省为文件内最早日期；
  - `--scope`：owned（默认，只导 `daily_universe` 里的代码）或 market（受源契约 §9.6 的 `RESEARCH_MARKET_SCOPE_ENABLED` 把关）。
- 执行顺序（任一步失败就整次拒绝，零写入，退出码非 0）：
  1. **只扫描 A 股 .day**：文件名须为 sh、sz、bj 加 6 位数字加 .day；经 `trades.normalize_code` 规范化后，只保留 `securities` 里 type 为 stock 且 listing_status 为 listed 的代码。其余文件不打开、不计算哈希，只按原因计数（非 A 股、规范化失败、非 listed）。
  2. **自己生成 sha256 清单**：对第 1 步留下的每个文件算 sha256，写成清单落盘到 `--audit-dir`（文件名含本次运行的北京时间与 run 编号）。清单每行为「sha256、字节数、相对路径」，末行为文件数与清单自身的 sha256。dry-run 也生成清单。
  3. **复跑比对**：`--audit-dir` 里若已有上一次清单，逐项比对，输出新增、删除、变化的文件数。通达信客户端会在收盘后往 .day 追加新行，所以「变化」不算错误，只记录；比对结果与清单 sha256 写进 pipeline_runs。
  4. **防读到半截文件**：解析完一个文件后再算一次 sha256，与第 2 步不同即视为导入中被改写，该文件拒绝并计数，整次运行为 partial；不影响其他文件。
  5. 校验 D；解析与单位自检；按 `UPSERT_BATCH_ROWS` 分批写入 trade_date 在 [from, D] 内的行。
- 解析：每条 32 字节，小端 `<IIIIIfII`；日期非法、高低价矛盾、价格为 0 的记录拒绝并计数。
- 单位自检（逐文件）：成交额 ÷ 成交量须落在当日 [low, high] 内（容差 1%）；不满足的比例超过 5% 时整文件拒绝，记 `tdx_unit_suspect:<code>`。
- 幂等：写入只经 `upsert_daily_bars`，DO NOTHING；同样参数重复运行，第二次 inserted 为 0、行数不变。一次性动作，可重复运行。
- 记录：每次运行写一条 pipeline_runs，stats 含清单 sha256、文件数、导入行数、跳过数（按原因）、冲突数、拒绝数、复跑比对计数；不写宿主路径。
- 不出网：模块不得 import 任何 egress 或 transport。

### 3.4 截止日期 D（推荐不变）

- D 为麦蕊 3 年回填起点的前一个开市日。起点 = 以 `_default_trade_date` 为 trade_date、`backfill_window_days(conn, trade_date, 3)` 窗口的第一个开市日；dry-run 打印推荐值，`--until` 晚于它即拒绝。
- 理由同 T-A142：整段导入会让通达信先写入重叠期，麦蕊后到时 DO NOTHING，快照又排除 `tdx_local`，持仓的日报历史窗口会出现缺口。重叠期交给交叉核对 CLI。

### 3.5 Windows 与容器

- 宿主路径含中文与空格（§1.1）。O1 须在用户电脑上用 dry-run 确认容器内能列出三个 lday 目录且 A 股文件数与预期同量级（约 5,600），否则不进入 `--apply`。
- 路径一律由参数给出、用 pathlib 解析；目录名大小写不敏感地匹配；日期按 Asia/Shanghai 判定今天。
- CLI 以普通用户运行，对 `--root` 只读，不需要写权限；只对 `--audit-dir` 写。

### 3.6 分钟线 .lc1 / .lc5（T-A143 起改为必需，移到 `intraday-bars.md`）

- 格式要点（公开资料，未实测核对）：每条 32 字节；前 2 字节为打包日期（年 = 值整除 2048 再加 2004，余数整除 100 为月，余数模 100 为日），接着 2 字节为当日零点起的分钟数；随后 open、high、low、close、成交额为 float32，成交量为整数，最后 4 字节保留。.lc1 为 1 分钟、.lc5 为 5 分钟。
- 覆盖很短（约 133、287 个交易日），对日 K 链路没有用处。
- ~~本期不导入、不建表、不建迁移、不拷出。~~ T-A143：依用户原话「日内做T 不需要分钟线？」改为必需，导入、存储、迁移都见 `intraday-bars.md`。本 CLI 仍只处理 .day。

## 4. 下游边界

- `daily_snapshot._load_bars` 增加条件：source 不是 `tdx_local`（NULL 与 mairui 照旧）。因此 owned 快照、analyze、日报、today 都看不到通达信行，`OWNED_VERSION` 不变。
- 研究读取入口本单不定，另开单；它可以读 `tdx_local`，但须在结果里保留 source。

## 5. 交叉核对

- 命令：`daily-bars-crosscheck-tdx`，参数为 `--root`、`--audit-dir`（先做 §3.3 的第 1–4 步）、`--from`、`--until`、`--scope`；只读，不写 daily_bars。报告写进 `--audit-dir`。重叠期（麦蕊回填起点以后）的比对都靠它。
- 对象：同一代码同一日期，麦蕊行（source 为 mairui）与 .day 记录。
- 比对规则：
  - open、high、low、close：到分完全相等；
  - volume：完全相等（两侧均为股）；
  - amount：|差| ≤ max(1 元, |麦蕊值| × 2.4e-7)（float32 相对精度的 2 倍；1e9 量级约 ±240 元，覆盖 T-A136 的 ±64 元估计）；
  - 只在一侧有：单列为 missing_in_mairui 或 missing_in_tdx，不视为差异。
- 报告格式：写到 `--audit-dir` 下的文件（JSON Lines，每行一项）：code、trade_date、field、mairui_value、tdx_value、tolerance、kind（mismatch、missing_in_mairui、missing_in_tdx）；末行为汇总（比对键数、各 kind 计数、超差率）。同时写一条 pipeline_runs 汇总，不写明细。
- 「另行记录、不覆盖」：核对结果只进报告文件与运行汇总，不改 daily_bars 任何行。

## 6. 迁移

- 新迁移 0033（单头由 0032 变为 0033）：把 `ck_daily_bars_source_allowed` 改为 source 为 NULL 或属于 fake、mairui、tdx_local。不改已有行，不加列。
- downgrade：存在 source 为 tdx_local 的行时拒绝；否则恢复 0032 的约束。

## 7. 待用户提供 / 确认

| # | 内容 | 保守默认 |
| --- | --- | --- |
| U-T0 | 是否同意把通达信 vipdoc 下的 lday（及分钟线目录）只读挂进容器并导入（T-A143 按未答处理；目录本身用户已给出，§1.1） | 不挂载，不导入 |
| U-T1 | 同一键已有通达信行、麦蕊后到时，是否让麦蕊替换。用户说「以麦蕊为准」，但主键一键一行，DO NOTHING 会让先到的通达信行留下 | 麦蕊也 DO NOTHING，快照排除 `tdx_local`，日报不受影响；需要替换时另开单（替换前先写核对报告） |
| U-T2 | 「兜底」补的行是否允许进入日报的历史窗口 | 不允许，只供研究 |

## 8. 验收（G/W/T）

开发时点：§3–§6 全部现在就能做（离线、不出网，用构造的临时目录测）；真正挂载与 `--apply` 要等用户同意（U-T0）；§5 与真实麦蕊行的比对要等单 D 之后库里有麦蕊行。

后端（新单 T1：迁移与导入）：
- `test_migration_0033_allows_tdx_local`（新，迁移测试）：Given 升到 0033 / Then 写 source 为 tdx_local 的行成功，写其他未知值失败；有 tdx_local 行时 downgrade 拒绝。
- `test_tdx_cli_generates_manifest`（新，不连库；取代 T-A142 的 `test_tdx_manifest_mismatch_rejected`）：Given 构造的 sh/sz/bj lday 目录 / When dry-run / Then `--audit-dir` 下生成清单，行数等于 A 股文件数，每行 sha256 与字节数正确，末行含清单自身 sha256；库零写入。
- `test_tdx_rerun_compares_manifest`（新）：Given 上一次清单存在，本次一个文件被追加、一个被删除、一个新增 / Then 比对计数为变化 1、删除 1、新增 1，写进 pipeline_runs；运行不因此失败。
- `test_tdx_file_changed_during_import_rejected`（新）：Given 打桩让某文件解析前后的 sha256 不同 / Then 该文件拒绝并计数，运行为 partial，其他文件照常导入。
- `test_tdx_root_missing_lday_rejected`（新）：Given `--root` 下缺 bj/lday / Then 退出码非 0，零写入。
- `test_tdx_audit_dir_must_be_writable_and_outside_root`（新）：Given `--audit-dir` 不可写，或位于 `--root` 之下 / Then 拒绝。
- `test_tdx_rows_after_until_not_imported`（新）：Given 文件含 D 之后的记录 / When `--apply --until D` / Then 库里该代码最大 trade_date 不晚于 D。
- `test_tdx_until_after_mairui_window_start_rejected`（新）：Given `--until` 晚于由 `backfill_window_days` 推出的麦蕊回填起点的前一开市日 / Then 拒绝；dry-run 打印推荐 D。
- `test_tdx_import_rerun_idempotent`（新）：Given 同一目录、同样参数运行两次 / Then 第二次 inserted 为 0，表行数不变。
- `test_tdx_import_readonly_mount`（保留，改写）：Given `--root` 为只读目录（测试里以 chmod 去掉写权限模拟），进程对它没有写权限 / When `--apply` / Then 成功；`--root` 内容与 mtime 不变，清单只出现在 `--audit-dir`。
- `test_tdx_parse_record_layout`（新，不连库）：Given 一条构造的 32 字节记录（虚构代码 000001.SZ）/ Then 日期、OHLC ÷100、成交额 float32、成交量正确。
- `test_tdx_import_filters_stock_listed_only`（新）：Given 目录内有 A 股、基金/ETF、指数、板块（880 开头）、债券、已退市股票各一 / Then 只导入 listed 的 A 股，其余计入跳过数，按原因分列；被过滤的文件不进清单、不被打开。
- `test_tdx_import_do_nothing_on_existing`（新）：Given 同键已有 mairui 行且值不同 / When `--apply` / Then 原行不变，冲突数为 1。
- `test_tdx_import_no_suspended_inference`（新）：Given 文件缺某开市日 / Then 该日没有任何行，is_suspended 不被写。
- `test_tdx_import_unit_selfcheck_rejects_file`（新）：Given 成交量按手写入的构造文件 / Then 整文件拒绝，记 `tdx_unit_suspect:<code>`。
- `test_tdx_import_until_must_be_past_open_day`（新）：Given `--until` 为今天、未来、休市日 / Then 拒绝；dry-run 默认不写库。
- `test_tdx_import_ignores_minute_files`（新）：Given lday 目录内混入 .lc1、.lc5 / Then 分钟文件不进清单、不解析、不写入，计入跳过数。
- `test_tdx_import_no_network`（新）：Given 打桩 `egress.mairui_get` / Then 调用数为 0。
- `test_snapshot_excludes_tdx_local`（新，连库，测试隔离库）：Given 某持仓代码在窗口内只有 tdx_local 行 / When build / Then 快照里该代码没有这些 bar，按既有规则记缺口。
- `test_backfill_ready_ignores_tdx_local`（新）：Given 窗口内全是 tdx_local 行 / Then `backfill_ready` 为 False。

后端（新单 T2：核对）：
- `test_crosscheck_tolerance_amount_float32`（新）：Given amount 差 200 元、量级 1e9 / Then 不算 mismatch；差 300 元 / Then mismatch。
- `test_crosscheck_report_jsonl_shape`（新）：Then 每行字段恰为 §5 所列，末行为汇总。
- `test_crosscheck_read_only`（新）：Then daily_bars 行数与内容核对前后相同。

运维（新单 O1：只读挂载，须用户本人同意）：
- Given 用户本人明确同意挂载与导入（U-T0）/ When 运维在用户电脑的部署 env 文件里写入 vipdoc 宿主路径，compose 以 `:ro` 把 sh/lday、sz/lday、bj/lday（以及 `intraday-bars.md` 的 minline、fzline）挂到后端容器 / Then 容器内可读、写入失败；compose 文件与代码里没有任何具体宿主路径，未设置该参数时 compose 不挂载、服务照常启动。
- Given 挂载完成 / When `docker compose run --rm` 跑 `daily-bars-import-tdx` 的 dry-run / Then 打印 A 股文件数、跳过数、清单位置、推荐 D；用户确认后才加 `--apply`。
- Given 用户未同意 / Then O1 不执行，默认不导入。
- Given 用户撤回同意 / Then 运维去掉该卷与 env 参数；已导入的 tdx_local 行是否删除，另问用户。
