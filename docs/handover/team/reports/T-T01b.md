# T-T01b 报告：测试对齐契约 v0.2.2

- 角色：测试；工作区 `/workspace/wt-tests-T-T01`，分支 `test/T-T01`，基于 `23fb8b7`
- 提交：**`d745148`**（仅本地，**未推送**；推送需用户批准）
- 只改 `tests/`。未调用麦蕊或任何真实行情 API，未使用真实密钥。本报告不含任何原始敏感值。
- 依据：`/workspace/team/reports/T-A02.md` 清单；文档以本地 main `a42bce7` 为准（`git fetch` 后 origin/main `96c1c8e` 更旧），导出到 `/tmp/aia-v022`。

## 1. 架构师决定的落实
- BUSINESS 配置深合并，列表整体替换：现有用例保留，并新增显式用例 `test_config.py::test_business_list_replaced_wholesale`。
- 导入用例数按 **54** 计入：`tests/README.md` 和 `fmt_a/README.md` 均已改为 54。

## 2. 改动清单
| 文件 | 改动 |
|---|---|
| `backend/api_app/test_contract_v022.py`（新增） | v0.2.2 预言函数与用例，均含正例和反例：RuleRef（`passed: boolean\|null`）、`rule_ids_passed`、P1b（role ∈ {entry, exit, weakening} 且 passed = true；只有 veto、只有 null、只有模型等反例）、DimensionCell（只计 entry/filter/hold）、horizon-assessments（scores 四个整数键且不为 null；reasons 带 horizon/polarity；inputs_missing；position_open_close 触发）、G-01（LIMIT_LOCKED 不把状态改成 vetoed）、risk_warning 上限。另有文档一致性用例，以及 `/admin/*` 匿名访问 404（5 组方法×路径）。后端缺实现的用例按依赖 skip。 |
| `backend/api_app/test_meta_enums.py` | 期望版本 v0.2.2；后端仍报 v0.2.1 时 xfail，原因写明 T-B01；新增契约头版本用例；`needs_action` 必须是 bool；码表改用 `unit/import_codes.json`。 |
| `backend/api_app/test_health.py`、`conftest.py` | 桩函数改为返回 ComponentHealth/IngestHealth 枚举成员（后端用 `is` 比较）；新增 FakePipeline（redis `pipeline(transaction=False)`）。 |
| `backend/api_app/test_config.py`、`test_config_yaml_defaults.py`、`config_defaults/`（由 `config_defaults_v0_2/` 改名，新增 `llm.yaml`） | 列表整体替换用例；llm/market_rules/horizon 相关用例按依赖 xfail。 |
| `backend/api_app/test_errors_and_validation.py` | /admin 错误方法的 skip 原因改为“v0.2.1 起统一 404，依赖 T-B03”。 |
| `backend/contract/test_contract_live.py` | `/health`、`/health/ready` 在 OpenAPI 已声明 503（db/redis down，契约 §7.10）时，豁免 `not_a_server_error` 检查；响应体仍按 schema 校验。 |
| `backend/unit/import_codes.json`（由 `import_codes_v0_2.json` 改名） | **文件名去掉版本号**（plan 原写 `_v0_2_2`，这里选了版本中立的名字，避免每次升版都改名）；标注 api-contract v0.2.2 §4.1；仍为 46 个码。 |
| `backend/unit/test_expected_json.py` | 新增对账成本预言（含分红），容差 max(0.01, 0.1%×券商值)，等于容差不算差异；RC-COST 参数化用例、分红降低成本用例、契约文本用例；后端用例 skip，依赖 T-B19/T-B18。 |
| `fixtures/broker_statements/fmt_a/expected.json` | 契约标为 v0.2.2；新增 `reconciliation_cost_cases` RC-COST-01..05（全部为合成数据）。 |
| `tests/README.md`、`fmt_a/README.md` | v0.2.2、54 个用例、新文件名。 |

## 3. 测试结果
| 环境 | 结果 |
|---|---|
| v0.2.2 后端（`AIA_*_DIR=/tmp/aia-v022`，live 契约指向自起的 uvicorn :18080，db/redis 不可达） | backend + replay：**459 passed，0 failed，89 skipped，10 xfailed**（6 个 subtest 通过） |
| 默认环境（工作区内无 src/backend，97 个 api_app 用例 skip） | **306 passed，0 failed，252 skipped** |
| integration（testcontainers） | 4 passed |
| vitest | 9 passed |
| Playwright（1440×900 深色，端口 4399） | 2 passed，2 skipped |
| `generate.py --check` | **通过**（0 个文件不同） |

10 个 xfail（`xfail_strict=true`，后端修好后会转为 XPASS 失败，提醒移除标记）：
- null 合并（T-B02）
- api_key_env 被误判为敏感键（T-B25/T-B02）
- BUSINESS_FILES 缺 llm（T-B25）
- 模型拒绝 market_rules（T-B36）、horizon（T-B30）、llm（T-B25）
- 仓库 yaml 与契约默认值不一致：market_rules（T-B36）、horizon（T-B30）
- 仓库缺 llm.yaml（T-B25）
- meta 版本仍为 v0.2.1（T-B01）

## 4. 扫描（范围：相对 23fb8b7 的改动 + 未跟踪文件，共 19 个文件）
- gitleaks（docker，`--redact`）：**no leaks found**。
- S1–S9 规则计数：
  - S2 hex32+ 命中 22 处，全是 fmt_a/README.md 里合成夹具文件的 sha256；
  - S5 命中 1 处，是 test_config.py 的 `FAKE…` 占位值；
  - 其余均为 0。
  - 结论：无真实敏感值。
- 原始样本泄漏扫描：从 `/workspace/team/samples` 提取 150 个特征 token，命中 3 个。3 个都是 horizon_classifier.yaml 里的整数阈值（形如 X0000000 的整数），属于偶合，**无原始样本泄漏**。
- 临时扫描脚本和目录已删除。

## 5. 失败与阻塞（按负责人）
- **T-B01**：`app/schemas/enums.py` 和 meta 的 `CONTRACT_VERSION` 仍为 v0.2.1，需改为 v0.2.2。
- **T-B02**：BUSINESS 覆盖值为 null 时的合并语义未实现。
- **T-B25**：需新增 `config/llm.yaml` 并把 llm 加入 BUSINESS_FILES；`api_key_env`（只是变量名）被敏感键检查误拒，需放行（与 T-B02 协同）。
- **T-B30**：`/horizon-assessments` 路由、`Recompute.on` 的 position_open_close 触发、horizon 配置均缺失。
- **T-B36**：`app.market_rules` 为空；MarketRuleSegment 缺 modeled_from、adv_basis、risk_warning。之后由 T-T19 补单测。
- **T-B18/T-B19**：对账成本未计入分红；后端用例在 skip。
- **T-B33/T-B34/T-B42**：RuleRef 三值（passed 可为 null）、rule_ids_passed、P1b、DimensionCell、G-01（LIMIT_LOCKED 不改为 vetoed）均未实现。之后由 T-T17 做 LIMIT_LOCKED 端到端测试。
- **T-B03**：/admin 鉴权的完整场景（已登录）待实现。匿名访问 404 已通过。
- **运维/部署**：8080 上另一个 agent 部署的 nginx（aia-nginx-1）对 TRACE 返回 405 但没有 `Allow` 头，违反 RFC 9110。用默认 `AIA_CONTRACT_BASE_URL` 跑会产生 4 个 live 子失败。需要在 nginx 配置里补 `Allow` 头，或把该路径交给后端处理。本次改用自起的 :18080 后端验证，结果为 0 失败。

## 6. 说明
- 码表文件改名为 `tests/backend/unit/import_codes.json`，引用方已全部更新。
- 未改动 src、docs、deploy、CI、samples；共享工作树只读；未影响 aia-*、ci-drill-* 容器。
