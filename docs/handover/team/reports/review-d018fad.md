# 评审 d018fad（tester：修 6670b10 的 7 个失败用例，分支 test/T-T01）

- 评审人：项目架构师；时间：2026-11-01 20:25（America/Denver，UTC-7）
- 方式：只读。git archive d3be426（后端 `uv sync --frozen`）后，用 d018fad 的 tests/ 整体替换导出里的 tests/，在导出目录里装 tests/requirements.txt 和 pytest-cov。按 CI 的方式跑 `pytest -c tests/pytest.ini tests/backend tests/replay`，测试库用 testcontainers 起的临时容器。没有改仓库，没有推送，没有调用麦蕊。
- 对照：review-6670b10.md §4 给 tester 的待办（7 个用例，摘掉 11 个 XPASS）。

## 结论：可以推送（有条件）

7 个用例都改对了，在 d3be426 上全部通过。但 main 在本提交之后又加了 0018（9e693b2）、0019（1398351）两个迁移，所以 `test_alembic_head_is_known` 在当前任何后端提交上都是红的（M1）。另外还有 3 组已知变化要跟进（M2–M4）。都不是本提交引入的错误，但 tester 分支合入 main 之前必须处理完，否则 backend 任务会一直红。

## 1. 实测（d018fad 的 tests + d3be426 的后端）

`12 failed（7 个用例 + 5 个 test_contract_live 子用例）/ 1138 passed / 97 skipped / 52 xfailed / 14 xpassed / 6 errors`，用时 259s。

| 项 | 结果 |
|---|---|
| review-6670b10 指出的 7 个用例（a11_09、t_t24 ×3、t_t25c ×2、head 0017） | 前 6 个**通过** ✓；head 用例见 M1 |
| aia_maint 夹具 | 按被测树 deploy/db/roles/grants.sql 的 `$maint$` 段建角色（LOGIN NOSUPERUSER … NOINHERIT，随机口令，DSN 写进 tmp_path 下 0600 文件，经 `AIA_MAINT_DATABASE_URL_FILE` 传入，不打印）✓。授权段直接取自被测树，所以 7f3f9ba（aia_maint 收窄为列级授权）之后会自动跟上，这个设计是对的 |
| 摘掉 11 个 xfail | ✓ 都已转为普通断言并通过 |
| test_auth_t_b03.py::test_alembic_head_is_known | **失败**：`'0018' in ('0008',…,'0016','0017')`（test_auth_t_b03.py:265 的 KNOWN_HEADS） |
| test_meta_enums.py ×4（parsers_sanity、v025、v027、v028） | **失败**：契约错误码表有 60 行，用例写死 59 行（4b40e5c 在契约里加了 414 URI_TOO_LONG） |
| test_rulings_t_b46_47_t_t25d.py::test_r6_* | 1 个失败、6 个 setup error：`POST /trades` 400 `qty: Input should be a valid string`。原因是 9e693b2 按 R11 #9 收紧了 schema（qty/price 必须是字符串），用例发的是数字 |
| test_config_yaml_defaults.py::test_snapshot_equals_plan_block[securities] | **失败**：plan §6.1 的 securities.yaml 多了 `master` 段（T-A04），快照没同步 |
| test_contract_live（5 个子用例） | 打的是本机默认 BASE_URL 上别人起的服务，不算 |
| XPASS 还剩 14 个 | 12 个 `test_etf_without_data_source_always_t_plus_1[*]`（9e693b2 修了 m2，空串也按 T+1）；1 个 `test_r8_openapi_has_pattern`；1 个 T-B30 用例（见 §3） |

## 2. 问题

**B：无。**

**M**
- **M1 KNOWN_HEADS 缺 0018、0019。** 位置 tests/backend/api_app/test_auth_t_b03.py:265。修法：加上 "0018"、"0019"；或者改成从被测树的 alembic versions 目录里读 head，只断言"只有一个 head"，以后加迁移就不用再改。→ tester
- **M2 test_meta_enums 写死错误码 59 行。** 改成 60 行并把 URI_TOO_LONG 加进期望集合；最好按契约表逐行比对，不再写死计数。→ tester
- **M3 R6 夹具按旧 schema 发数字 qty/price。** test_rulings_t_b46_47_t_t25d.py 里建交易的辅助函数改为发字符串（契约 v0.2.9 R11 #9）。现在 6 个 R6 用例都在 setup 阶段报错，等于没测 /portfolio。→ tester
- **M4 securities 快照没同步 plan §6.1 的 master 段。** → tester

**m**
- m1 12 个 ETF 用例和 test_r8_openapi_has_pattern 已稳定 XPASS（实现已在 9e693b2），可以摘掉 xfail。→ tester
- m2 T-B30 那个 XPASS 的 reason 写的是"GET /horizon-assessments 尚未实现"，这已经不是事实了，见 §3。→ tester

## 3. T-B30 的 XPASS（父代理要求单独定位）

- **用例**：tests/backend/api_app/test_auth_t_b03.py:1062–1078 `test_v025_horizon_assessment_has_hints_and_classifier_1_2_0`，`xfail(strict=False, reason="后端 T-B30（周期分类器 1.2.0 与 GET /horizon-assessments 尚未实现；T-A06 §3）")`。
- **它断言了什么**：novice 画像下 GET /horizon-assessments?security_code=600000 → 200；`classifier_version == "1.2.0"`；`hints` 是列表、每项正好有 horizon/rule_id/text；hints 含 SH0C、IT0C，且 caps 里没有这两条。
- **为什么会过**：不是碰巧。T-B47（c9e1e73）已经交付 GET 和分类计算。config/horizon_classifier.yaml:5 是 `classifier_version: "1.2.0"`；SH0C/IT0C 在 :90 起是 `mode: hint` 的画像规则，app/strategy/horizon/classifier.py:142–172 在画像不满足时只写进 hints[]、不写 caps。这几条规则只依赖 profile.experience 等画像字段，不依赖 f.* 特征，所以用例的断言是被真实代码满足的，结果是稳定的。
- **T-B30 / T-B30a 的验收算不算达成：没有。** plan 第 3189 行写明"T-B30 以 T-B30a 完成为验收前提"。目前还缺：
  1. T-B30a 的 15 个 f.* 特征没有落地，分类结果靠 data_missing 封顶；
  2. 结果没有写进 symbol_horizon_assessments（on_demand），snapshot_id 是 uuid5 算出来的（app/strategy/horizon/inputs.py:168），不是 data_snapshots 里真实存在的 id（契约 #27 ⑧）。0018 只放开了 CHECK；
  3. 导入确认、加自选、每周触发这几种重算触发都没有；
  4. 没有生成 proposed 状态的 strategy_instances。
- **建议**：把这个用例的 xfail 摘掉，归属改为 T-B47（它测的是已经交付的接口层行为）。另外为 T-B30 的真正验收写 xfail 用例：结果落库并且 snapshot_id 能在 data_snapshots 里查到、同输入同记录、trigger=on_demand、f.* 齐全时不再被 data_missing 封顶。t25d 里已经有一部分，按这四条补齐。→ tester；实现 → 后端 T-B30a/T-B30

## 4. 推送后 CI
tester 分支本身不跑 main 的 CI。合入 main 之后 backend 任务的 pytest 会**红**：M1–M4 一共 7 个失败、6 个 error（归 tester）。test_contract_live 依赖外部服务，CI 里应当跳过，需要 tester 确认 CI 里没有设 BASE_URL。

## 5. 谁做什么
- tester：M1–M4、m1、m2；补写 T-B30 验收用例。
- 后端：T-B30a、horizon 结果落库（契约 #27 ⑧）。
