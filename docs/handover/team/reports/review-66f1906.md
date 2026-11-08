# 评审 66f1906（T-B48 p11：因子嵌套解析、截断不算前视、p11_replay 离线重放）

- 评审人：项目架构师；时间：2026-11-01 19:45（America/Denver，UTC-7）
- 方式：只读，在 /tmp 的干净导出里做；把已有运行目录 results/run-20261101-190106 复制到导出里重放（results/ 已被 gitignore）。全程没有证书变量，没有调用麦蕊。

## 结论：可以推送

## 1. 实测
- `selfchecks/tb48_p11.py`：**38 passed / 0 failed**，其中包括“自检全程未尝试出网”。
- p11_replay 离线重放，三道护栏都验证了：
  1. Python 审计钩子监控 socket.connect、getaddrinfo、http.client.connect：重放过程中网络事件为 0。
  2. 在没有网络的命名空间里跑（`unshare -rn`）：照样正常完成，网络调用被拦截 0 次。
  3. 设了证书变量（填的是假值）就拒绝运行，退出码 3 ✓。
  4. 在 `no_network()` 里主动去调 socket.create_connection、requests.get、common.call：三个都抛 NetworkBlocked，hits=3 ✓（hits 不为空时 replay 判失败，退出码 2）。
- 重放结果：原来的运行把 profit_yoy 和 roe_ttm 判成 `lookahead_suspected`，重放后判为 `consistent_with_pit`（各有 after_plrq 5 次、precision_only 2 次）。这 2 次精度变化是 2026-08-03 和 08-14 的 6 位截断，例如 1.<account> ↔ 1.471418。我逐条看过，确实只是截断，不是跳变。同一天 history 和 batch 的值相等 ✓。GAP7：factor/all 85、factor/list 85 ✓。
- 输出写到 `p11_gaps.replay-T-B48.json`，原文件 p11_gaps.json 没被覆盖 ✓。

## 2. 问题
**B：无。**

**M1 `precision_only` 的判定太宽，会把真实变化当成精度差。** 现在用两个数里较少的小数位数 k，只要四舍五入或截断到 k 位后相等就算精度差。我实测下面这些都判成了 True：15.0→14.97、1.5→1.47、20.0→19.6、100→99.6、3.0→2.9999。一个因子值只要碰巧是整数或一位小数，真实的跳变就会被当成精度差排除掉，`lookahead_suspected` 可能因此漏报。本次数据不受影响（结论已核对），但 T-B05 复测 3 要靠这个判定。建议同时满足：较短一方的小数位数 ≥ 4（或者明确较短一方 = 较长一方截断或四舍五入到 k 位，且 k ≥ 4），并且 |x−y| < 10^(−k)；自检补一条反例（20.0→19.6 必须是 False）。→ 后端，T-B05 复测之前修好

**m**
- m1 `batch_values`：items 里找不到请求的代码、但只有一条时，会直接拿那一条，可能把别的代码的值当成 600519 的。建议对不上就返回空，并记一条证据。
- m2 记录发现（不是代码问题）：factor/batch 请求的是 trade_date=20260417，实际返回的 trade_date 是 20260130。说明 batch 的 trade_date 参数不是“按这一天取值”，T-B05/数据源文档要写清楚它的语义。现在的代码已经改成按实际返回的日期比对，这是对的。
- m3 重放的历史序列只由“首值 + 跳变点”重建，前提是跳变点明细没被截断（每类最多 8 条）；不完整时会抛错，这是对的。README 里可以注明：跳变超过 8 条的因子没法重放。

## 3. 谁做什么
- 后端：M1（T-B05 复测之前），m1，m3（文档）。
- 数据源/架构师：m2 写进 T-B05 和数据源说明。
