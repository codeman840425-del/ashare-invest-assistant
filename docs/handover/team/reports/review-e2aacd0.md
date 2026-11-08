# 评审：e2aacd0 feat(frontend): planned 状态显示 + 风险标记文案按契约 #29

评审人：项目架构师　时间：2026-11-01（America/Denver）　方式：只读，/tmp 干净导出，pnpm 串行

## 结论：可推送（前端无 B/M）；后端有 1 项待提交

## 文案核对
| 值 | 前端标签 | 前端提示 | 契约 §3 / #29 | 后端 |
|---|---|---|---|---|
| st | 其他风险警示 | 其他风险警示（ST） | 其他风险警示（ST） | — |
| star_st | 退市风险警示 | 退市风险警示（*ST） | 退市风险警示（*ST）；#29 ① star_st = 退市风险警示 | 一致 |
| delisting | 退市整理 | 证券简称带“退”的退市整理标记 | 证券简称带“退”的退市整理标记；#29 ① delisting = 退市整理 | 见 M-后端 |

- 前端已无其他“退市风险”误用于 delisting 的字符串（grep 确认）。
- SecuritySearch、StockPage 加了 tooltip 和 data-testid；新测试 planned-riskflag.test.tsx 是前端 colocated 测试，不越权。
- #31、#32 前端列不受影响。

## 问题
- **M（后端，非本提交）**：HEAD 上 `content.py` 对 delisting 仍是“该证券处于退市风险警示状态”，与 #29 不符。最终文案“该证券处于退市整理期（简称带“退”）”（T-B49）目前只在另一代理的**未提交**工作区改动里，本次未动。上线前后端须提交 T-B49。
- n：`risk_flag=delisting` 与 `listing_status=delisting_period` 同时出现时会并列显示“退市整理”“退市整理期”两个标签，语义重复但不错，可后续合并显示。
- n：mock 里 admin 候选 `status=planned` 且 `plan_ids=[]`，按 #21（“planned 只由系统写入…本版无入口”）是不会出现的状态；已注明“仅演示”，可接受，建议改成带一个 plan_id 更贴近真实。

## 验证
- c4329bc 导出（含本提交）：typecheck 0、lint 0、vitest 串行 584 通过 / 1 跳过。新增的共享 planned mock 没有带坏其他用例。

## 谁做什么
- 后端：提交 T-B49 的 content.py 文案（M，上线前）。
- 前端：无必改；n 项可选。
