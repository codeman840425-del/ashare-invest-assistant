# T-R42｜补 T-R41 G7 核对表策略侧证据（T-R43 按 T-A83 修订）

产物（均在本目录；不改 lifecycle / 不推 / 不调麦蕊）：

| 脚本 | 对应项 | 说明 |
|---|---|---|
| `cost_replay.py` + `cost_replay_cases.json` | H14 / S14 | 【虚构】成本滑点确定性回放 + 手算 oracle；冲击成本（impact_tiers）与成本放弃阈值**未建模**，登记于 gaps（T-R43 删除死分支） |
| `compliance_lint_local.py` | H16 / S16 | 本地禁用词自查（照录 plan:3362/162、reviews.py:317-324）；不替代服务端 `decide()` lint（reviews.py:351/:353） |
| `hypothesis_structure_check.py` | H4 / S3 | 仅结构检查（T-R43 修正 why_it_works 空值跨行漏检）；语义审核见 T-R47 `g7_review` §1A/§2A：S3 改一致（架构师 T-A111 :10 复核通过），H4 经 T-R49 按 v3 复审（§1B）改一致，架构师 T-A115 :3 复核通过 |
| `null_propagation_replay.py` + `null_propagation_fixtures.json` | （H18 **不构成证据**） | **本脚本不读取夹具行情/特征求值规则，只按 K 线根数验证参考层预热→null→insufficient_data 逻辑，不构成 H18 证据**（T-A83 B-1）；H18 自 T-R46 起以后端正式用例 `test_h18_h01_fx8_null_propagates_to_insufficient_data`（T-T48，T-A86）为证据记「一致」，与本脚本无关 |

G7 核对表初核计数（T-R53b 后）：合计 40；**一致 39 / 不一致 0 / 缺证据 1**（H-01 20/0/0；S-01 19/0/1：仅 S18，须用户本人答复；H12/S12 按 T-A118 ②③ 与 team 报告 T-R53-dbproof 改一致，库例需 o61、离线不覆盖；T-R53 时 37/0/3；T-R50/T-R52 时 36/0/4；H4 按 H-01 v3 改一致，架构师 T-A115 :3 复核通过；T-R50 按 v3 重核 20 个 H 行无状态变化；T-R43 时 32/0/8，T-R44 时 33/0/7，T-R46 时 34/0/6，T-R47/T-R48 时 35/0/5），以 `T-R41/g7_review_H-01_S-01.md` §5 为准；用户勾选仍未勾。

运行：`python3 <script>.py` 与 `python3 -O <script>.py` 均 exit 0（含内置篡改自检：每个篡改都须被拒且原因与被篡改项逐字对应）。
`python3 <script>.py --mutate <name>`：对输入做**真实篡改**后走同一校验，exit 1 并输出对应原因；未知 name 列出可选项（exit 2）；若篡改未被识别则输出 MUTATION_NOT_DETECTED 且 exit 0（不再无条件失败）。
