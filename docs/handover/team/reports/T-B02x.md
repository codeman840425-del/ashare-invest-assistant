# T-B02x：契约 v0.2.6 核对，以及导入/成交规则（T-F02 D3/D5/D7）

**结果：已完成。提交 `f739296`，只在本地，未 push。范围限于纯规则；还没有导入、成交、持仓的接口，所以端点没做。**

## 1. 契约 v0.2.6 核对
对照文档 3cb8af1（契约 v0.2.6）检查了下列各项，全部一致：
- `/meta/enums` 的 version 为 `v0.2.6`。
- 枚举：`data_licence_status`、`data_licence_tier`，`notification_kind` 含 `data_licence`，`gap_reason` 含 `data_licence_unavailable`，`card_risk_level`，`registration_mode` 三值。
- 错误码：59 个，与契约逐一相同，含三个 `DATA_LICENCE_*`。
- `HorizonCap.kind` 只有 `gate|data_missing`（迁移 0006，提交 38ed2b5）。
- `Me.data_licence_status`，以及 `/me/data-licence*` 和 `/admin/data-licences*`（efcd244）。
- reason_codes 22 个，import_codes 46 个。

v0.2.6 里还没做的部分：
- SSE `data_licence` 事件：还没有 SSE 基础设施。
- `manual_refresh` 返回 `409 DATA_LICENCE_UNAVAILABLE`、行情接口的 `data_status`/`gaps` 降级：还没有行情接口。
- `market.*` 的 `source_licence_id`：见 T-B04a-x 报告。

## 2. 本次新增（纯函数）
- **`app/importing/resolutions.py`**：按契约 §4.1“处理选项”表实现 10 个提示码。
  - `resolution_choices` 与 `default_resolution` 按表给出，取表中第一个为默认。
  - `validate_resolution` 只要求该码的选项非空，不看 `needs_action`，所以 39/40 也能覆盖。
  - 覆盖类选项（`force_import`、`keep_import_void_manual`、`confirm_new_holder_code`）的 `reason` 必填，去掉首尾空白后 1–200 字，否则返回 `400 VALIDATION_ERROR`，`fields` 给出 `choice`/`reason` 和 issue。
  - 表里出现未登记的提示码时，模块导入即失败。
- **`app/domain/trades.py`**：
  - 作废理由 1–200 字；用户不能自己写 `batch_reverted:` 前缀。批次回滚用 `batch_reverted:{batch_id}`。
  - 已作废的成交再作废 → `409 INVALID_STATE_TRANSITION`。
  - 带 `corrects_trade_id` 时 `reason` 必填。
  - `trade_out()` 把库行映射成契约 `Trade`：
    - `replaces_trade_id` → `corrects_trade_id`，`quantity` → `qty`；
    - `fee_total` 是四项费用之和，全为空时为 null；
    - `trade_time` 取北京时间；
    - `csv_template` 来源对外报为 `import`。

  库列名和契约字段名不同，只在 API 层做映射，不需要迁移。
- 自测 `/tmp/tb02/selftest_tb02x.py` 61/61：直接解析契约 §4.1 的表，与代码逐码比对。ruff 和 mypy 都没有报错。

## 3. 未做（需要 imports/trades/portfolio 端点任务）
以下端点后端还没有实现，本次只提供上面的规则，供实现时直接调用：
- `POST /imports/{batch_id}/findings/{finding_id}/resolve`
- `GET /imports` 列表元素 `ImportBatchSummary`
- `GET/POST /trades`
- `POST /trades/{id}/void`
- `GET /portfolio?account_id=`（D7）

## 4. 注意：契约 v0.2.7 已经提交（fa6d55d，北京时间 06:38，T-A08）
用最新文档跑 tester 套件，有 3 个失败（`test_contract_header_version`、`test_contract_parsers_sanity`、`test_plan_6_1_lists_eight_files`）。原因是测试常量还是 v0.2.6：`CODE_COUNTS` 里没有 v0.2.7 的计数，plan §6.1 的配置文件也新增了 `securities.yaml`，从 8 个变成 9 个。

换成 v0.2.6 文档（3cb8af1）跑：531 passed / 0 failed。

- **tester**：给测试补上 v0.2.7 的常量。
- **编排者/架构师**：后端要跟进 v0.2.7，需要新开任务：`CONTRACT_VERSION`、18 个新枚举、`data_provider` 加 `exchange`、`config/securities.yaml` 及加载器、`strategy_instances` 加列和 `origin=system`、securities 系列端点等。本轮按指令只对齐 v0.2.6，没有动这些。
