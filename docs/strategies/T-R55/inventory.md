# T-R55 只读盘点｜src / tests / config / deploy 中与 S-01 v1（055105a）绑定的写死处

> 只列不改。基线：strat/T-R55（基 strat/T-R53@281f524，拣入 T-R54）。方法：在 src、tests、config、deploy 四个目录用 rg 检索 S-01 的 key、card_id、卡文件名、fixture 编号、提交号 055105a/fe2afa5/4c00ae7、库内 S-01 审核号前缀，以及卡内容哈希字样；逐处人工打开上下文判断。未连库、未调麦蕊、未读凭据。

## 1. 结论

- 写死 S-01 `version_no=1` 的后端代码、配置或部署脚本：**0 处**。
- 写死 055105a 提交号、S-01 卡内容 sha256 或库内 S-01 审核号的地方：**0 处**。
- 间接依赖 055105a 内容（fixture 个数）的断言：**1 处**（下表 #2），在 281f524 上已是红的，与本次升号无关。
- 其余命中都是按文件名读现行卡或按 key 引用，不绑版本，升 v2 后自动读 v2。

## 2. 清单

| # | 文件:行 | 中文转述 | 是否绑定 v1 / 055105a | 处理建议（只列，不改） |
|---|---|---|---|---|
| 1 | `src/backend/selfchecks/test_tb100_delivery.py:47-48` | 导入器离线预检自检：按 key 拼出三张正式卡（含 st_pullback_ma）的现行文件路径传给导入器 | 否（读现行文件） | 无 |
| 2 | `src/backend/selfchecks/test_tb100_delivery.py:68` | 断言导入器输出「三卡、golden 共 34 个通过」。34 = H-01 11 + W-01 15 + S-01 **8**，S-01 的 8 是 055105a 的夹具数；4c00ae7 起现行卡为 10 个，实际输出 36 | **是（间接绑 055105a 夹具数）** | 归后端：改为 36 或改为按卡计数。T-R55 在 281f524 与新 HEAD 上各亲跑一次，均输出 36、该用例失败（既有问题，非升号引入） |
| 3 | `tests/backend/unit/test_g7_h12_s12_s20_exec_t_t63.py:48` | 用例按路径读现行 S-01 卡 | 否 | 无；T-R55 在 v2 上离线重跑通过 |
| 4 | `tests/backend/unit/test_g7_h12_s12_s20_exec_t_t63.py:222`、`:257`、`:347` | 按夹具编号取 S01-FX6、S01-FX1 | 否（编号在 v2 未变） | 无 |
| 5 | `src/backend/app/strategy/universe_norm.py:8` | 文档字符串说明 screen 为空时 v1 不扫全市场，引用 S-01 卡与 T-A83 ④ | 否（指能力阶段，不是 version_no） | 无 |
| 6 | `src/frontend/src/mocks/strategyHandlers.ts:24-25` | 前端演示用 mock：st_pullback_ma 的当前版本号写为 1、生命周期写为已发布 | 演示数据，不连后端、不进库 | 可选：前端随后对齐；不影响导入与门禁 |
| 7 | `src/frontend/src/pages/t-f22.test.tsx:234-239`、`t-f22a.test.tsx:219-260` | 前端用例按 key 取 mock 模板并检查启用开关 | 否（只用 key） | 无 |
| 8 | `deploy/runbooks/wrapup-deploy.md:94`、`:253` | 部署手册只写了正式卡 v3 导入「待补」（指 H-01），未出现 S-01 | 否；但**缺 S-01 v2 导入步骤** | 归运维/编排者：收口部署时补 S-01 v2 导入与部署后只读 SQL（S-01 最新版本号为 2、v2 上 G1–G6 结果） |
| 9 | `config/`（含 `config/strategies/`、`config/engine_policy.yaml`） | 无 S-01 条目；`config/strategies/` 只有 H-01、W-01 两个文件 | 否 | 无 |

误命中已排除：`tests/backend/unit/import_cases.json:356` 的用例编号含 S-01 字样（持仓用例编号），`tests/backend/api_app/test_contract_v028_t_t23.py:514` 以 S-01 作模板 id 测 ETF 拒绝，均不涉版本。

## 3. 对导入的影响

库内已有 S-01 v1（055105a 内容）。v2 卡 version_no 为 2，导入时应作为新版本行写入，不触发同号改内容的冲突（`src/backend/app/strategy/cards/persistence.py:118-120`）；是否真能导入以后端在目标环境实跑为准，本角色只做了离线预检（三卡 36 个 golden 全过）。

*T-R55｜策略研究员只读盘点；未改 src、tests、config、deploy。*
