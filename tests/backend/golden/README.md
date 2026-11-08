# tests/backend/golden —— 策略 / 建议 golden 用例

> plan §8.0「黄金样例」：给定"策略版本 + 数据快照 + 画像 + 持仓" → 期望的动作 / 分数 / 置信度 / 理由 / 反证 / 失效条件，
> **逐字段比较**；规则改动必须更新黄金文件并在 PR 中解释；门槛 100% 通过，黄金文件变更需评审。
> plan §2.5（G6）：每个模板至少 6 个 golden fixtures（满足、不满足、缺数据、维度分歧、涨跌停或停牌、做T 无底仓）。

## 目录
```
tests/backend/golden/
├── README.md
├── golden_compare.py      # diff_fields(expected, actual) → 不一致字段路径列表
├── test_golden.py         # 执行器：遍历 cases/**/*.json，按 subject 找被测函数，逐字段比对
└── cases/
    ├── _harness_selftest_*.json   # 执行器自检（用测试内的假实现，永远会跑）
    ├── strategy_eval_placeholder.json
    └── <strategy_key>/<场景>.json  # T-T10 按 "策略 × 典型快照" 添加
```

## 用例 JSON 格式
| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 全局唯一，如 `GOLDEN-MA_TREND-satisfied-001` |
| `subject` | 是 | 被测对象，映射见 `test_golden.py::SUBJECTS`（如 `strategy_eval` → `app.strategy.evaluator:evaluate`） |
| `description` | 否 | 场景说明（中文） |
| `input` | 是 | `{strategy_version, snapshot, profile, holdings}`；快照数值**虚构或来自脱敏回放**，不含真实账户信息 |
| `expected` | 是 | 期望输出，**完整**写出（多键、少键、列表顺序不同都算失败） |

## 比较规则
- 金额/价格/比例按 api-contract §1 用**十进制字符串**，严格相等，不做浮点容差；分数/置信度是 number，严格相等。
- 列表顺序是输出的一部分（理由、反证按实现约定的稳定顺序）。
- 失败信息只列字段路径（如 `expected.reasons[1].code`），便于评审。

## 流程
1. 新增策略或改规则 → 新增/更新 `cases/<strategy_key>/*.json`。
2. 在 PR 描述里逐条说明 golden 变更原因；评审通过才合并。
3. 实现模块落地后，在 `SUBJECTS` 登记 `subject → 模块:函数`；未登记或模块不存在的用例 skip（不是 pass）。
