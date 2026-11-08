# T004 券商 TXT 导入验收用例

> 作者：测试　日期：2026-11-01　关联：plan.md §3.5 / §3.5A，夹具目录 `tests/fixtures/broker_statements/fmt_a/`（说明见该目录 `README.md`，元数据见 `meta.json`，异常夹具由 `generate.py` 生成）
>
> 所有输入均为脱敏/虚构夹具，本文不含任何原始敏感值。下文“行 N”指夹具文件物理行号（从 1 起）。
>
> **变更记录**
> - v1（T004）：初版 53 条，错误码多为测试建议码，期望结果写在夹具 README §6。
> - v2（T-T01a，2026-11-01）：错误/提示码对齐 **api-contract v0.2**——行/文件级提示码以 §4.1（46 个，`error_codes` 之外的独立命名空间 `import_codes`）为准，上传/确认失败的 HTTP 码以 §4 为准（`IMPORT_FILE_ERRORS`、`IMPORT_ROW_ERRORS`、`IMPORT_WARNINGS_UNACKNOWLEDGED`、`IMPORT_NOTHING_TO_COMMIT`，均 422）；解析器 ID 改为 `tdx_trades_v1` / `tdx_positions_v1`（旧名 `fmt_a_*` 为别名）；期望结果迁入夹具目录 `expected.json`（唯一期望来源），README §6 改为引用；资金链/重复/缺期初等提示改用 §4.1 码（`IMPORT_CASH_CHAIN_BREAK`、`IMPORT_DUPLICATE_IN_DB`、`IMPORT_DUPLICATE_IN_FILE`、`IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL`、`IMPORT_MISSING_OPENING_POSITION`），`cash_gap` / `quantity_mismatch` 仍是对账项类型 `reconciliation_item_kind`；原“二选一/待定”中契约已定的部分按定稿改写（TC-ENC-08、TC-SIDE-04）。**原 53 条的编号、分组、顺序不变**；仅在 A 组末尾新增 TC-ENC-12（仅 CR 换行夹具 `trades_cr.txt`），合计 54。

## 0. 约定

- **前提 P0**：新建空账户 `acc-test`（无期初持仓、无历史成交），时区 Asia/Shanghai。
- **前提 P1**：在 P0 基础上已确认导入 `trades_sample.txt`（66 笔）。
- 码：行/文件级提示码一律取自 api-contract v0.2 §4.1（`import_codes`，含 severity 与 scope）；HTTP 失败码取自 §4（`IMPORT_FILE_ERRORS` 等）。`new` / `duplicate_in_db` / `duplicate_in_file` / `possible_duplicate_of_manual` 为 `dedup_status` 取值；`cash_gap`、`cash_chain_break`、`quantity_mismatch` 为 `reconciliation_item_kind` 取值（契约 §3）。逐行/逐文件的精确期望见 `fmt_a/expected.json`，本文与其冲突时以 `expected.json` 为准。
- 数值比较一律按 Decimal 字符串精确比较，除非注明容差。
- “错误行”不入库；“警告”可入库但须在预览中展示；“忽略”不入库、不计为错误。

## 1. 用例汇总

| 分组 | 编号范围 | 数量 |
|---|---|---|
| A 文件与编码 | TC-ENC-01 ～ TC-ENC-12 | 12 |
| B 格式识别与定宽对齐 | TC-FW-01 ～ TC-FW-08 | 8 |
| C 字段与数值解析 | TC-NUM-01 ～ TC-NUM-10 | 10 |
| D 买卖方向、撤单与非成交业务 | TC-SIDE-01 ～ TC-SIDE-05 | 5 |
| E 去重与幂等重导 | TC-DUP-01 ～ TC-DUP-08 | 8 |
| F 持仓快照与对账 | TC-POS-01 ～ TC-POS-05 | 5 |
| G 隐私与批次 | TC-PRIV-01 ～ TC-PRIV-04、TC-BATCH-01 ～ TC-BATCH-02 | 6 |
| **合计** | | **54** |

优先级：P0 = 首版必须通过；P1 = 首版应通过；P2 = 可延后。

## 2. 用例明细

### A 文件与编码

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-ENC-01 | P0 | P0；上传 `trades_sample.txt`（GBK、CRLF、无 BOM） | `detected_encoding` = gbk 或 gb18030；66 个证券名称均正确解码（如行 4 `示例甲业`、行 5 `科创甲`） | 预览中无 `�` 或乱码；名称与 `expected.json` 一致 |
| TC-ENC-02 | P0 | 上传 `positions_sample.txt` | 编码 gbk/gb18030；摘要行与明细中文正确 | 同上 |
| TC-ENC-03 | P0 | 上传 `trades_utf8.txt`（UTF-8 无 BOM） | `detected_encoding` = utf-8；5 行有效，字段值与 `trades_sample.txt` 行 4–8 逐字段相同 | 两次解析结果的规范化 JSON（去掉 row_no 外）完全相等 |
| TC-ENC-04 | P0 | 上传 `trades_utf8_bom.txt` | 依据 BOM 判为 utf-8；BOM 被剥离，行 1 仍识别为分隔线；5 行结果同 TC-ENC-03 | 第一条数据的“<field:date>”不含 `\ufeff`；结果与 TC-ENC-03 相同 |
| TC-ENC-05 | P1 | 上传 `trades_gb18030_ext_char.txt` | 严格 GBK、严格 UTF-8 失败，GB18030 成功 → `detected_encoding` = gb18030；行 4 名称 `示例䶮业`；2 行有效 | 名称码点正确（第 3 字 U+4DAE）；无错误行 |
| TC-ENC-06 | P1 | 上传 `trades_truncated_mid_char.txt`（末行在双字节汉字中间截断、无换行） | 编码仍判为 gbk/gb18030；行 4 有效；行 5 错误 `IMPORT_ROW_DECODE_ERROR`；文件级警告 `IMPORT_FILE_POSSIBLY_TRUNCATED` | 不整文件拒绝；不因末尾半个字符被 charset-normalizer 误判为其他编码；有效行数 = 1 |
| TC-ENC-07 | P0 | 上传 `empty.txt`（0 字节） | 文件级错误 `IMPORT_EMPTY_FILE`；上传返回 422 `IMPORT_FILE_ERRORS`（契约 §4），不创建批次 | 服务端无异常栈；`import_batches` 无新增记录 |
| TC-ENC-08 | P0 | 上传 `trades_header_only.txt` | 识别为 `tdx_trades_v1`；0 行；文件级警告 `IMPORT_NO_DATA_ROWS`；批次状态 `previewed` | 预览可展示；确认返回 422 `IMPORT_NOTHING_TO_COMMIT`（契约 v0.2 §4，已定稿） |
| TC-ENC-09 | P0 | 上传 `trades_lf.txt`（LF） | 5 行有效，字段值与 `trades_sample.txt` 行 4–8 相同 | 任一字段（尤其“备注”）末尾不残留 `\r`；与 TC-ENC-03 规范化结果相等 |
| TC-ENC-10 | P0 | 上传 `trades_blank_lines.txt` | 4 行有效（行 4、6、8、11）；空行、纯空格行、纯 Tab 行静默跳过 | 错误数 0、警告中不含空行相关项；`row_no` 为 4、6、8、11 |
| TC-ENC-11 | P1 | 上传 `trades_truncated_last_line.txt`（末行在“<field:trade-id>”中途截断） | 行 4–6 有效；行 7 错误 `IMPORT_ROW_TRUNCATED`；文件级警告 `IMPORT_FILE_POSSIBLY_TRUNCATED` | 有效 3、错误 1；数据库中不存在残缺<field:trade-id>的记录 |
| TC-ENC-12 | P1 | 上传 `trades_cr.txt`（仅 CR `\r` 换行，老 Mac 风格；T-T01a 新增） | 按 CR 切行；5 行有效，字段值与 `trades_sample.txt` 行 4–8 相同（同 TC-ENC-09） | 物理行数 9、`row_no` 为 4–8；不得把整个文件当成 1 行；字段末尾不残留 `\r`；与 TC-ENC-09 规范化结果相等 |

### B 格式识别与定宽对齐

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-FW-01 | P0 | `trades_sample.txt` | 格式 `tdx_trades_v1`（别名 `fmt_a_trades_v1`），置信度 ≥ 0.95；表头 20 列，列起点字节偏移 = 0,16,32,48,64,80,98,118,136,152,171,190,209,225,243,259,273,288,302,318 | 预览返回的 `parser_id` 与置信度满足要求；列映射与 README §4.2 一致 |
| TC-FW-02 | P0 | `positions_sample.txt` | 格式 `tdx_positions_v1`（别名 `fmt_a_positions_v1`）；表头 11 列，起点 0,12,28,44,61,78,93,108,126,144,163 | 同上 |
| TC-FW-03 | P0 | `trades_sample.txt` 全部 66 行 | 按 GBK 字节偏移切分（策略 a）与按 `\s{2,}` 切分（策略 b）逐行一致，每行 20 个字段；3 字名称（如 `科创甲`）与 4 字名称（如 `示例甲业`）所在行后续字段不偏移 | 0 条 `IMPORT_ROW_COLUMN_MISMATCH`；行 5“成交数量” = `-3000.00`（不粘连名称补齐空格） |
| TC-FW-04 | P0 | `trades_sample.txt` 数据行长度 365–371 字节不等（差异仅在行尾空格） | “备注”列取值仅为 `证券买入` / `证券卖出`，无尾随空格 | 66 行备注去重后恰为 2 个值 |
| TC-FW-05 | P0 | `trades_utf8.txt` | UTF-8 下按显示宽度（`east_asian_width` W/F=2）对齐，结果与 GBK 版相同 | 同 TC-ENC-03；不得按 UTF-8 字节偏移切分 |
| TC-FW-06 | P1 | `trades_extra_column.txt`（表头多“扩展标志”列，插在“成交金额”后） | 仍识别 `tdx_trades_v1`；文件级警告 `IMPORT_UNKNOWN_COLUMN`（列名“扩展标志”）；3 行字段值与 `trades_sample.txt` 行 4–6 相同 | 按表头名称取列；<field:order-id>/<field:trade-id>等后续列不错位（如行 4 <field:trade-id> = `-80000007`） |
| TC-FW-07 | P0 | `trades_missing_column.txt`（缺“成交价格”） | 不自动套用 `tdx_trades_v1`（或置信度 < 0.95）；文件级错误 `IMPORT_REQUIRED_COLUMN_MISSING`（成交价格） | 预览不可确认（确认返回 422 `IMPORT_FILE_ERRORS`）；不得由金额/数量反推价格后静默入库 |
| TC-FW-08 | P0 | `trades_column_mismatch.txt` | 行 4 有效；行 5 名称 `科创 甲`（单空格）两策略一致 → 有效，名称原样保留；行 6（成交数量左移 2 字节）→ `IMPORT_ROW_COLUMN_MISMATCH`；行 7（席位代码为空，仅 19 个 token）→ `IMPORT_ROW_COLUMN_MISMATCH` | 有效 2、错误 2；错误行的 `row_no` = 6、7 |

### C 字段与数值解析

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-NUM-01 | P0 | `trades_sample.txt` 行 4 | side=sell，quantity=77300，price=29.40000000，amount=2272620.00，net_amount=2271110.48，commission=227.26，stamp_tax=1136.58，transfer_fee=22.73，other_fees=122.95，traded_at=2026-10-09T10:44:33+08:00，market=SH | 逐字段 Decimal 精确相等 |
| TC-NUM-02 | P0 | `trades_sample.txt` 行 7 | price=51.94800000（8 位小数不丢失），amount=935064.00 | 使用 Decimal/NUMERIC 存储，读取回来字符串一致；代码中无 float 转换 |
| TC-NUM-03 | P0 | `trades_sample.txt` 行 30、42–48（5 位时间） | 行 30 `93005` → 09:30:05；其余 7 行同样左补 0 | 8 行 `traded_at` 均为合法时间，无 `IMPORT_INVALID_TIME` |
| TC-NUM-04 | P0 | `trades_sample.txt` 全部行 | 66 行 `｜数量×价格 − 成交金额｜ ≤ 0.0001`；`<field:amount> = ±成交金额 − (佣金+印花税+过户费+规费)` 全部精确成立 | 0 条金额类错误/警告 |
| TC-NUM-05 | P0 | `trades_sample.txt` 全部行 | 汇总：买入金额 11857466.62；卖出金额 11883080.85；<field:amount>合计 15776.12；佣金 2374.06、印花税 5942.19、过户费 237.42、规费 1284.44 | 预览汇总或入库后 SQL 汇总与之精确相等 |
| TC-NUM-06 | P0 | `trades_sample.txt` <field:trade-id>列 | 47 个负数编号（如行 4 `-80000007`）、19 个正数编号均作为字符串原样保存 | 不丢负号、不转科学计数法、不截断前导字符；10 位编号（如行 7 `-8000000021`）完整 |
| TC-NUM-07 | P0 | `trades_bad_formats.txt` 行 7、8 | 行 7 数量 `1,000.00` → 1000，时间 `93005` → 09:30:05；行 8 全角 `１０００.００` → 1000 | 两行有效，quantity = 1000 |
| TC-NUM-08 | P0 | `trades_bad_formats.txt` 行 4–6 | 行 4 日期 `20261332` → `IMPORT_INVALID_DATE`；行 5 时间 `256000` → `IMPORT_INVALID_TIME`；行 6 时间 `9305`（4 位）→ `IMPORT_INVALID_TIME` | 3 行错误、不入库；不对 4 位时间做猜测补齐 |
| TC-NUM-09 | P0 | `trades_sign_and_value_errors.txt` | 行 4 有效；行 5、6 `IMPORT_SIDE_QTY_SIGN_MISMATCH`；行 7 `IMPORT_INVALID_PRICE`；行 8 `IMPORT_AMOUNT_MISMATCH`（29500.00 vs 29400.00）；行 9 `IMPORT_INVALID_QUANTITY`（数量 0）；行 10 警告 `IMPORT_NET_AMOUNT_MISMATCH`（差 1.00） | 有效 2（行 4、10）、错误 5；错误行号逐一对应 |
| TC-NUM-10 | P1 | `trades_sample.txt` 印花税列 | 23 笔卖出印花税均 > 0；43 笔买入印花税均 = 0 | 费用列映射正确（净佣金→commission，印花税→stamp_tax，过户费→transfer_fee，交易规费→other_fees） |

### D 买卖方向、撤单与非成交业务

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-SIDE-01 | P0 | `trades_sample.txt` | 买入 43 笔（数量为正）、卖出 23 笔（数量为负 → 存为正数 + side=sell）；买卖标志与备注（证券买入/证券卖出）一致 | 计数精确；库中 quantity 全部 > 0 |
| TC-SIDE-02 | P0 | `trades_sample.txt` | 600/601/688 开头 → SH，且<account-field>为 `A…`（17 行）；00/30 开头 → SZ，<account-field>为 `0…`（49 行） | 市场推断与<account-field>前缀 100% 一致，无冲突警告 |
| TC-SIDE-03 | P0 | `trades_cancelled.txt` | 行 4（买 1000）、行 8（卖 500）有效；行 5（买入撤单）、行 6（买卖标志“撤单”）→ 忽略 `IMPORT_ROW_CANCELLED`；行 7（废单）→ 忽略 `IMPORT_ROW_REJECTED` | 入库 2 笔；错误 0；<field:trade-id> `0` 未进入去重键；600001 持仓 = 500 |
| TC-SIDE-04 | P1 | `trades_non_trade_events.txt` | 不生成任何 trade；行 4 → event `dividend` +1234.50；行 5 → `other` −123.45（plan 3.5A-1 规则 7：股息红利税暂记 other，待范本）；行 6 → `ipo_allot` 301002 500 股；行 7 → 跳过 + 警告 `IMPORT_UNKNOWN_BIZ_TYPE`，不入库 | trades 表无新增；时间 `0`、编号 `0` 不触发时间/编号错误 |
| TC-SIDE-05 | P1 | P0；`trades_sample.txt` | 行 4–7 四笔卖出无前序买入 → 4 条 `IMPORT_MISSING_OPENING_POSITION` 警告，证券 600001、688001、688002、688003 | 警告数 = 4；这些证券不得以负数持仓作为正常持仓展示（具体呈现待定） |

### E 去重与幂等重导

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-DUP-01 | P0 | P0；`trades_sample.txt` | 66 行全部 `new`；虽有 15 个<field:order-id>跨交易日重复（如 `9001`、`901`），但不判重 | 规则 1 键 = H(账户\|交易日\|市场\|<field:trade-id>)，66 个键互不相同 |
| TC-DUP-02 | P0 | P1；再次上传同一 `trades_sample.txt` | 文件级警告 `IMPORT_DUPLICATE_FILE`（sha256 相同；v0.2 不再是 409 HTTP 错误，上传照常 201）；66 行全部 `duplicate_in_db` + `IMPORT_DUPLICATE_IN_DB`，新增 0 | 确认后 trades 表行数不变；持仓、现金不变 |
| TC-DUP-03 | P0 | P1；上传 `trades_reimport_overlap.txt` | 行 4–6 `duplicate_in_db`（`IMPORT_DUPLICATE_IN_DB`；行 5 另有 `IMPORT_CASH_CHAIN_BREAK`）；行 7–8（20261030 301002 买 1000 <at>33.00 / 卖 1000 <at>33.50）`new` | 确认后新增 2 笔；301002 持仓仍为 0；末笔<field:balance> 6559459.23 |
| TC-DUP-04 | P0 | P0；`trades_duplicates_in_file.txt` | 行 4–6 `new`；行 7（与行 5 完全相同）`duplicate_in_file`（`IMPORT_DUPLICATE_IN_FILE`）；行 8（<field:trade-id>同行 6、日期 20261012）`new`，并提示 `IMPORT_CASH_CHAIN_BREAK` | new 4、duplicate_in_file 1；确认后只入 4 笔 |
| TC-DUP-05 | P0 | P0；对 `trades_sample.txt` 的同一预览，用同一 `Idempotency-Key` 连续调用确认 2 次（含并发） | 两次返回同一批次结果；只入库一次 | trades 表 66 行，不是 132 行 |
| TC-DUP-06 | P1 | P0；`trades_cancelled.txt` 后再上传 `trades_cancelled.txt` | 第二次：行 4、8 `duplicate_in_db`；行 5–7 仍为忽略 | <field:trade-id> `0` 的行不会互相判重为同一笔，也不会入库 |
| TC-DUP-07 | P1 | P0；先手工录入一笔与 `trades_sample.txt` 行 4 相同（日期、证券、方向、数量、价格）的成交，再导入 `trades_sample.txt` | 行 4 标记 `possible_duplicate_of_manual`（`IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL`），默认不自动合并，由用户选择 | 预览中该行有提示；用户确认“跳过”后 trades 表只有 1 笔该成交 |
| TC-DUP-08 | P2 | P0；构造：将 `trades_sample.txt` 行 4 的<field:trade-id>列清空（复制到临时文件，不改夹具） | 回退到规则 2：<field:order-id>+交易日+市场+方向+证券代码 作为去重键 | 同一文件重复两次该行时第二行为 `duplicate_in_file` |

### F 持仓快照与对账

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-POS-01 | P0 | `positions_sample.txt` | 文件级警告 `IMPORT_SNAPSHOT_AS_OF_ASSUMED`、`IMPORT_SNAPSHOT_TOTALS_MISMATCH`；摘要：CNY；余额=可用=可取=6558986.88；参考市值 3910635.00；资产 10481539.03；盈亏 −451611.65 | 逐项 Decimal 相等 |
| TC-POS-02 | P0 | `positions_sample.txt` | 明细 1 行：002001 深市辛号，数量 202100，可卖 202100，成本 21.5698，现价 19.3500，市值 3910635.00，浮盈 −451611.65，比例 −10.291，market=SZ | 逐项相等；数量存为 Decimal |
| TC-POS-03 | P1 | `positions_multi_currency.txt` | 人民币摘要解析（参考市值 4079325.00、资产 10650229.03、盈亏 −447921.65）；`美元:` 行警告 `IMPORT_UNSUPPORTED_CURRENCY` 并忽略；明细 2 行（002001 SZ、688001 SH 3000 股 成本 55.0000 现价 56.2300 市值 168690.00 浮盈 3690.00 比例 2.236） | 警告 1 条；明细行数 2；美元金额不进入任何人民币汇总 |
| TC-POS-04 | P0 | P1；导入 `positions_sample.txt` 并对账 | 002001 数量一致（202100）；自算移动加权成本 4359245.63/202100 ≈ 21.5697 与券商 21.5698 一致（容差 0.01）；对账项 `cash_gap` = −0.02（提示）；无 `quantity_mismatch` | 对账结果中仅出现 `cash_gap` 提示和 4 只缺期初证券的提示，无错误 |
| TC-POS-05 | P1 | P1；查看资金链校验结果 | 7 行 `IMPORT_CASH_CHAIN_BREAK` 警告（对账项 `cash_chain_break`）：行 19（−0.04）、22（−0.02）、30（−0.02）、42（−0.06）、60（−0.01）、65（−0.03）、68（−0.02） | 提示数量与位置、金额精确一致；不阻断入库 |

### G 隐私与批次

| ID | 优先级 | 输入 | 期望输出 | 判定标准 |
|---|---|---|---|---|
| TC-PRIV-01 | P0 | P1 | <account-field>仅以 HMAC + 掩码（`A****`、`0****`）保存；共 2 个不同 HMAC；席位代码丢弃；`raw_line`（如保留）中<account-field>已掩码、席位代码已去除 | 全库与应用日志中检索 `<account>`、`0000000001`、`90001`、`900002` 均无命中 |
| TC-PRIV-02 | P1 | P0；`trades_column_mismatch.txt` 导出错误报告 | 错误报告含行号、错误码、掩码后的原始行 | 报告中不出现<account-field>明文与席位代码 |
| TC-PRIV-03 | P0 | 仓库 `tests/` 目录 + 原始样本（仓库外）作为词表 | 泄漏扫描命中 0（已执行：`fmt_a/` 全部文件含 generate.py、meta.json、README，13 类敏感值，多编码匹配，0 命中） | 每次新增/修改夹具后重新执行，命中数必须为 0 |
| TC-PRIV-04 | P1 | `fmt_a/` 目录 | `python3 generate.py --check` 退出码 0；`meta.json` 开头含 `# SYNTHETIC`；目录内每个 `.txt` 都在 `meta.json.files` 中且 sha256 一致 | 任一不满足即失败 |
| TC-BATCH-01 | P0 | P0；`trades_sign_and_value_errors.txt` 选择“仅导入有效行” | 入库 2 笔（行 4、10），错误行生成可下载报告 | 批次状态记录有效 2、错误 5；错误行不影响有效行 |
| TC-BATCH-02 | P1 | P1；对 `trades_sample.txt` 批次执行“整批撤销” | 66 笔全部作废/删除；持仓与现金重算回到导入前（空） | 撤销后持仓为空；再次导入同文件时 66 行为 `new`（或按 plan 规定的状态），不残留重复键冲突 |

## 3. 覆盖矩阵

| 要求项 | 用例 |
|---|---|
| 持仓解析 | TC-ENC-02、TC-FW-02、TC-POS-01～03 |
| 成交解析 | TC-ENC-01、TC-FW-01、TC-FW-03、TC-NUM-01～06 |
| 编码识别（GBK/UTF-8/BOM/GB18030/截断） | TC-ENC-01～06 |
| 换行（CRLF/LF/仅 CR） | TC-ENC-01、TC-ENC-09、TC-ENC-12 |
| 中文定宽对齐 | TC-FW-03～05、TC-FW-08、TC-ENC-05 |
| 数值解析（Decimal、千分位、全角、负号） | TC-NUM-01～09 |
| 买卖方向 | TC-SIDE-01、TC-NUM-09 |
| 撤单/废单 | TC-SIDE-03、TC-DUP-06 |
| 异常（空文件、只有表头、缺列、多列、错位、截断） | TC-ENC-07～11、TC-FW-06～08 |
| 重复导入幂等、按<field:trade-id>去重 | TC-DUP-01～08 |
| 对账与资金链 | TC-POS-04、TC-POS-05、TC-SIDE-05 |
| 隐私与合成标记 | TC-PRIV-01～04 |

## 4. 疑点与待确认

1. 夹具已按 plan.md 放在 `tests/fixtures/broker_statements/fmt_a/`。`# SYNTHETIC` 标记写在 `meta.json` 开头的 `"marker"` 键、`generate.py` 和 README 中，TXT 夹具本身不加，以保持字节布局不变。两个主夹具是人工脱敏的派生文件，不由 generate.py 生成，与 plan.md“只允许生成脚本产生的文件”的 CI 规则需要协调；`expected.json` 已于 T-T01a 提供（唯一期望来源），README §6 改为引用。
2. CI <account-field>扫描（plan 7.4A S5/S6）会命中虚构值 `<account>` / `0000000001`；T-T01a 已在 `meta.json.fake_identifiers` 列出完整豁免集合与逐文件命中次数，待 DevOps 按此放行。
3. ~~错误码为测试建议~~：v0.2 §4.1 已定稿 46 个提示码及 severity；“<field:amount>不符”= warning（`IMPORT_NET_AMOUNT_MISMATCH`），“只有表头”= warning + 确认 422 `IMPORT_NOTHING_TO_COMMIT`；“名称含空格”仅空白不同不报 `IMPORT_NAME_MISMATCH`（§4.1 #35）。
4. 撤单/废单、红利、新股入帐等行的真实写法未见真实样本，夹具为推测构造。
5. 券商“资产”与“浮动盈亏”的口径未知（与自算不等），用例只要求展示不报错。
6. 缺少期初持仓时的持仓呈现方式（负数/待补录）plan.md 未定。
7. 虚构证券代码可能与真实证券重合，测试环境需要相应的证券主数据种子。
8. 未覆盖：超大文件性能、同一文件混合编码（仅 CR 换行已由 TC-ENC-12 覆盖；超限类 `IMPORT_FILE_TOO_LARGE` / `IMPORT_TOO_MANY_ROWS` 等无固定夹具的码由 `expected.json.generated_cases` 生成输入覆盖）。
