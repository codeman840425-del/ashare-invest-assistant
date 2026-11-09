# T-R42｜补 T-R41 G7 核对表策略侧证据

产物（均在本目录；不改 lifecycle / 不推 / 不调麦蕊）：

| 脚本 | 对应项 | 说明 |
|---|---|---|
| `cost_replay.py` + `cost_replay_cases.json` | H14 / S14 | 【虚构】成本滑点确定性回放 + 手算 oracle |
| `compliance_lint_local.py` | H16 / S16 | 本地禁用词自查（照录 plan:3362/162、reviews.py:317）；不替代服务端 |
| `hypothesis_structure_check.py` | H4 / S3 | 仅结构检查；语义仍缺证据 |
| `null_propagation_replay.py` + `null_propagation_fixtures.json` | H18 | 参考层 null→insufficient_data；实盘归编排者 |

运行：`python3 <script>.py` 与 `python3 -O <script>.py` 均 exit 0；`--mutate` 下 exit≠0。
