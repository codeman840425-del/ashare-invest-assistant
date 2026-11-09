# T-R42｜补 T-R41 G7 核对表策略侧证据（T-R43 按 T-A83 修订）

产物（均在本目录；不改 lifecycle / 不推 / 不调麦蕊）：

| 脚本 | 对应项 | 说明 |
|---|---|---|
| `cost_replay.py` + `cost_replay_cases.json` | H14 / S14 | 【虚构】成本滑点确定性回放 + 手算 oracle；冲击成本（impact_tiers）与成本放弃阈值**未建模**，登记于 gaps（T-R43 删除死分支） |
| `compliance_lint_local.py` | H16 / S16 | 本地禁用词自查（照录 plan:3362/162、reviews.py:317-324）；不替代服务端 `decide()` lint（reviews.py:351/:353） |
| `hypothesis_structure_check.py` | H4 / S3 | 仅结构检查；语义仍缺证据（T-R43 修正 why_it_works 空值跨行漏检） |
| `null_propagation_replay.py` + `null_propagation_fixtures.json` | （H18 **不构成证据**） | **本脚本不读取夹具行情/特征求值规则，只按 K 线根数验证参考层预热→null→insufficient_data 逻辑，不构成 H18 证据**；H18 初核为「缺证据」（T-A83 B-1） |

G7 核对表初核计数（T-R43 后）：合计 40；**一致 32 / 不一致 0 / 缺证据 8**（H-01 16/0/4、S-01 16/0/4），以 `T-R41/g7_review_H-01_S-01.md` §5 为准；用户勾选仍未勾。

运行：`python3 <script>.py` 与 `python3 -O <script>.py` 均 exit 0（含内置篡改自检：每个篡改都须被拒且原因与被篡改项逐字对应）。
`python3 <script>.py --mutate <name>`：对输入做**真实篡改**后走同一校验，exit 1 并输出对应原因；未知 name 列出可选项（exit 2）；若篡改未被识别则输出 MUTATION_NOT_DETECTED 且 exit 0（不再无条件失败）。
