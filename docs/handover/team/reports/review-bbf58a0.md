# 评审 bbf58a0（T-B46：/accounts、/imports、/trades、/portfolio，迁移 0014）

评审人：架构师 · 2026-11-01（America/Denver）· 方式：只读，`git archive bbf58a0` 导出到 /tmp/rv-bbf，在干净副本中运行；未改动工作区。

## 结论
**有条件通过**：没有 B 级问题。鉴权与跨用户隔离、<account-field>脱敏、无硬编码密钥都合格。有 3 个 M 级问题（/portfolio 响应字段与契约 v0.2.9 #1–#2 不一致；/portfolio 不读日线导致“其他行 estimated=false”无法成立；本提交没有仓内测试），需要后端在下一单（T-B46-x）修复后由测试员复测。m 级问题可以在同一单里顺手修。

## 问题清单

### M（必须修）
| # | 位置 | 问题 | 要求 |
|---|---|---|---|
| M1 | `src/backend/app/api/v1/portfolio.py` 第 64–75 行（`Position`）、第 78–86 行（`Portfolio`） | 持仓行字段是 `instrument_kind: str`，契约 §7.2 第 798 行与 v0.2.9 #1–#2 是 `security_type: security_type \| null`；顶层多出 `estimated`（契约没有）；`cash`、`total_assets`、`cost_price`、`weight_pct` 在模型里可为 null，契约写的是非空 | 按 T-B46-47 裁定 R6：改为 `security_type`（不在主数据中为 `null`）；删除顶层 `estimated`；`cash`、`total_assets`、`weight_pct`、`cost_price` 的可空性按裁定 R6 写入契约后对齐 |
| M2 | `portfolio.py` 第 5 行（文档串）、第 204–205 行 | 现价只取持仓快照的 `last_price_ref`，不读 `market.daily_bars`。只有成交流水、没有快照的股票持仓全部变成 `estimated=true`、`market_value=null`，与契约“其他行 `estimated=false`”矛盾 | 按裁定 R6：现价优先取该证券最近一个交易日的日线收盘价（库里已有的数据，不触发取数），没有日线时才用快照参考价，都没有才是 `estimated=true` |
| M3 | 整个提交 | 新增 4 组端点和迁移 0014，但仓内没有新增后端测试（只靠测试员的外部用例） | 补最小单元/接口测试：跨用户 404、导入两步提交、`valid_rows_only`、成交更正与作废、/portfolio 估算行 |

### m（建议修）
| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `portfolio.py` 第 327–365 行 | 只要有持仓就追加 `exposure.sector` 缺口，`data_status` 永远是 `partial` | 行业数据未接入前保留这条 gap，但 `data_status` 按 1.1 节取各项中最差的；行业暴露缺口单独不改变持仓本身的状态（裁定 R6 ③） |
| m2 | `api/v1/imports.py` 第 183 行 | `ResolveIn.reason` 的 OpenAPI 上限 1000，契约是 ≤200（`importing/resolutions.py` 第 105 行在业务层按 200 判，结果对，但 schema 不一致，会产生 schemathesis 误报） | OpenAPI 改 `maxLength: 200` |
| m3 | `api/v1/accounts.py` 第 35 行 | `alias`、`broker_name` 上限 32、`broker_name` 必填，契约只写“只接受 alias 和 broker_name” | 已在裁定 R11 写进契约（1–32），后端不用改 |
| m4 | `api/v1/trades.py` 约第 234–259 行；`imports.py` 约第 465–478 行 | 列表的 `?account_id=` 传他人或不存在的账户时返回空列表；`/portfolio?account_id=` 同样情况返回 404 | 统一为 404 NOT_FOUND（裁定 R11） |
| m5 | `importing/pipeline.py` 第 346 行 | `log.exception` 会把异常消息写进日志；目前解析层已把带原文的 `ValueError` 吞掉（`preview.py` 第 239–243 行），残余风险低，但没有兜底 | 只记录异常类型和批次号，不记录 `str(exc)`；`common/logging.py` 加一个对 6 位以上数字串与<account-field>模式的脱敏过滤器 |
| m6 | `api/v1/imports.py` 第 442 行 | 写了原始文件的 `retained_until`，但没有清理任务 | 登记到后端待办：周期任务按 `retained_until` 删文件（plan 3.5A 保留期） |
| m7 | `src/backend/app/cli/delete_user_data.py`（imports_root 解析） | CLI 的目录优先级 `AIA_IMPORTS_DIR > IMPORT_STORAGE_PATH > /srv/...`，API 在 local/test 下退回 `<tmp>/aia-imports`，开发环境 CLI 找不到文件 | 两处共用同一个解析函数 |
| m8 | `importing/keys.py`、`importing/storage.py` | 加密文件头只有 `v1`，没有密钥编号，`APP_MASTER_KEY` 轮换后旧文件无法区分 | 文件头加 `kek_id`（可以是 KEK 的 HMAC 前 8 字节），轮换方案登记运维 |
| m9 | `api/v1/trades.py` void 审计 | 审计 `detail` 存了作废理由全文 | 与 plan §7.3 清洗口径一致：理由属于自由文本，删除用户时整体删除（见追加裁定 B） |
| m10 | 迁移 0014 downgrade | 价格回退到 4 位小数会截断（已在迁移注释中说明） | 无需改，记录在案 |

## 逐项核对
- 路径、方法：/accounts GET/POST、/imports 全套（上传、列表、详情、行、options、resolve、confirm、discard、revert、errors.csv）、/trades GET/POST、/trades/{id}/void、/portfolio 与契约 §7.2 一致。
- 错误码与枚举：`IMPORT_FILE_ERRORS`、`IMPORT_ROW_ERRORS`、`IMPORT_WARNINGS_UNACKNOWLEDGED`、`IMPORT_NOTHING_TO_COMMIT`、`INVALID_STATE_TRANSITION`、`INVALID_CURSOR` 都是契约中已有的码；`import_status`、`import_row_status`、`dedup_status`、`trade_side` 取值与顺序和 §3 一致。
- 分页：游标带 HMAC 签名与作用域，伪造或过期一律 `400 INVALID_CURSOR`。
- 幂等：`/imports/{id}/confirm`、`POST /trades` 支持 `Idempotency-Key`，作用域含用户与路径。上传不带幂等键（重复文件给 `IMPORT_DUPLICATE_FILE` warning，符合契约）。
- 跨用户：`owned_account`/`_owned_batch`/`_owned_trade` 都按 `user_id` 过滤，他人资源 404（列表筛选除外，见 m4）。
- user_id 与删除清单：新增列都挂在已在 plan §7.3 删除清单中的表（`app.import_batches`、`app.import_rows`、`app.trades`、`app.broker_position_snapshots`）上，带 `user_id` 或经账户关联。
<redacted:identity-or-account-line>
<redacted:sensitive-value-or-command>

## 测试结果
| 项目 | 结果 |
|---|---|
| 后端自带 pytest（`src/backend`，uv） | 通过 |
| ruff check / ruff format --check / mypy --strict | 通过 |
| `scripts/ci/check_contract.py` | 2 项失败，都是已知的 v0.2.9 未实现项（版本号 v0.2.8；缺 T-A11 的 4 个枚举），与本提交无关 |
| `scripts/ci/check_code_namespaces.py` | 通过 |
| scripts/ci 测试 | 在带 .git 的副本中 200 通过、55 跳过（裸导出缺 .git 时 21 个失败，属环境原因） |
| 测试员用例（tests/backend + tests/replay，后端 venv，Docker 可用） | **877 通过，0 失败**，61 xfail、6 xpass（xpass 为注册关闭裁定已在 f72b8c7 实现，测试员需去掉标记） |
| gitleaks（提交区间） | 0 命中 |

## 谁要做什么
- **后端**：T-B46-x 修 M1–M3、m1、m2、m4–m9（M1、M2、m1 按 T-B46-47-rulings.md R6）。
- **测试员**：/portfolio 用例按 R6 改断言（`security_type`、无顶层 `estimated`、有日线的行 `estimated=false`）；加列表筛选他人账户 → 404 用例；去掉已转绿的注册关闭 xfail。
- **运维**：m8 密钥轮换方案；m6 清理任务的调度。
