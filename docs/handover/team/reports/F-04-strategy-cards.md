# F-04 策略知识卡前端接入（/strategy-cards）

基线 `origin/main=465e020`，分支 `ds/F-04`。F-01 核清的最大缺口：后端 4 端点 + 导航入口都在，前端零接入。

## 改动（只动 src/frontend/）
- `api/cardTypes.ts`（新）：列表项（契约 §7.4 九字段）、详情（plan §2.5.14 B 节字段全集 + `field_epistemic`/`refs`/`validation_summary`/`risk_level`/`gates_missing`）、版本历史、`FeatureCatalogItem`（逐字段对齐后端 `strategy/cards/models.py`）。
- `api/cardQueries.ts`（新）：列表（游标翻页取满）、详情、指定版本、版本历史、feature-catalog。
- `api/enums.ts`：新增 `card_completeness`、`card_source_kind`（取值照后端 `schemas/enums.py` 与表约束）。
- `mocks/cardHandlers.ts`（新）：3 张合成卡片（promoted / runnable_candidate / draft 三档），详情、版本历史、catalog；名称与出处均为合成示例。
- `pages/strategies/StrategyCardsPage.tsx`（新）：列表 + 完整度/周期筛选，风格对齐 StrategiesPage。
- `pages/strategies/StrategyCardDetailPage.tsx`（新）：假设、维度、入场/反向/失效/离场四段规则、数据需求、出处、外部验证信息、版本切换。
- `app/routes.tsx`：`strategy-cards` 与 `strategy-cards/:id` 从占位改为真实路由。
- `pages/strategies/t-f04.test.tsx`（新）：9 例。

## 关键守则（UI 不重算规则）
- `completeness` / `gates_missing` / `risk_level` **一律展示后端返回值**，前端不判断门禁是否通过、不把缺口翻译成“可以启用”。
- `validation_summary` 明确标注“来自研究员文档，产品不做回测”。
- 规则表达式的 `quantified` / `to_quantify` 如实展示为「已量化」/「待量化」。

## 验证
- `vitest run src/pages/strategies/t-f04.test.tsx` = **9/9**
- 回归 `t-f22.test.tsx` = 14/14；`t-f03.test.tsx` 单文件复跑 14/14（并行跑 t-f22+t-f03 时曾出现 1 例既有的等待超时抖动，单跑稳定通过，与本单改动无关）
- `secret_scan`（9 文件）= 0 阻断 0 告警；`git diff --check` = 0
- 未跑全量/coverage、未构建、未 typecheck（未授权）

## 移交项
- 卡片数量大时用 `MAX_PAGES` 上限翻页；当前卡片规模小，够用。
- 写入类端点（POST 卡片/新版本/晋级申请）不在本单范围，未接入。
- 来源许可展示（`sources[].license`）仅透传，未做许可合规判断（属架构/合规口径）。
- DeepSeek：未用，原因：字段逐条对齐契约与后端模型，不外包。
