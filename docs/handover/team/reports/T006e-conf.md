# T006e-conf 建议生成：画像不影响置信度（契约 v0.2.6 变更 11 / T006e 裁定 3 / plan I3、§3.3 第 3 点）

- 作者：后端；日期：2026-11-02；**结论：无代码可改，本任务无提交**

## 检查结果
- 后端目前**没有建议生成代码**：`src/backend/app` 中没有计算 `confidence` 的逻辑，也没有读取策略 `fit` 或 `mismatch_handling` 的代码（只有表列 `confidence` 与 CHECK 0–1）。
- 配置中没有“画像不匹配降置信度”的参数：`risk_controls.yaml` 只有 `executability.low_confidence_threshold: 0.4`（低置信度阈值，与画像无关）；`config/strategies/` 为空。
- 分类器的 `profile.*` 加分项（IT3、IT5、SH6、SH7 等）属于周期打分，不是建议置信度，按 plan §2.5.3 保持不变。

## 给以后实现建议生成的约定（实现任务须遵守）
- `confidence = 0.5×数据完整度 + 0.3×维度一致度 + 0.2×条件余量`，三项都**只来自信号证据**；`profile.*` 字段不得作为置信度的输入，也不计入“数据完整度”的必需特征（画像未填写不能拉低置信度）。
- 画像与 `fit` 不匹配只写 `warnings[]`/提示文字；相关画像字段未填写时不提示。
- 建议在黄金样例（plan §5 golden）中加一对用例：同一数据快照、不同画像 → `confidence` 完全相同。

## 发现的文档冲突（我不能改 docs/）
- `docs/strategies/_template.md` 第 291 行 `mismatch_handling` 仍写“不匹配时只提示并**降置信度**”，与契约 v0.2.6 变更 11、plan I3 冲突 → 请研究员/架构师改为“只提示，不降置信度”。
