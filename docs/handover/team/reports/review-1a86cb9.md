# 评审 1a86cb9（前端 m 修复：review-787e453 m1–m3、7f46681 m3/m4）：可推（位于 main 顶端，不在本段连续推送链内）
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- m1：前端不再写死任何板块的整手参数，只用服务端 lot_rule（min_buy/step）或草案 qty_range.lot；收到 lot_rule 之前，卖出只校验“不超过可卖数量”。
- m2：evidence id 先做 uuid 校验（lib/uuid.ts）再拼链接，否则只显示文本。
- m3：只有 4xx 换 Idempotency-Key；网络错误和 5xx（含 502/504）保留原键，这是正确的。
- 7f46681 m3/m4：未知 key 排到同级最后；errors.* 按码点排序，不再用 localeCompare。
- 实测：eslint、tsc 通过；vitest 705 例通过，1 例跳过。
- m：CandidateSignalDetailPage 第 1 行 import 的顺序与其余文件不一致，只是风格问题。
- B/M：无。
