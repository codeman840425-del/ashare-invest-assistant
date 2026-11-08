# 评审：f065f8d（T-B05 准备：precision_only 收紧、factor/batch 数据日期核对、p11/p12 复测开关、开关矩阵 dry-run、tb05_switches 自检）

- 评审人：项目架构师
- 时间：2026-11-01 20:25 MST（America/Denver）
- 方法：在 /tmp 的干净导出（git archive f065f8d）里跑；`env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY`，去掉代理变量；全程没有调用麦蕊。
- 范围：只评审，没有改仓库，没有推送。

## 结论

**可以推送（0 B / 0 M）。**
- precision_only 已按裁定收紧，两个反例 15.0↔14.97 和 20.0↔19.6 现在都判 False。
- 用上一次真实运行 run-20261101-190106 离线重放：§16 结论不变（两个因子都是 consistent_with_pit，precision_only=2），说明收紧没有改掉已有的合法精度差。
- T-B05 的麦蕊实测窗口不需要再等 f065f8d。

## 实测

| 项 | 结果 |
|---|---|
| 新旧 precision_only 对照（本地调用 `p11_gaps.precision_only`，旧实现照 f065f8d^ 原样重写后比较） | 15.0↔14.97：旧 True → 新 **False**<br>14.97↔15.0：旧 True → 新 **False**<br>20.0↔19.6：旧 True → 新 **False**<br>19.6↔20.0：旧 True → 新 **False**<br>100.0↔99.99999：旧 True → 新 False<br>0.5↔0.4999：旧 True → 新 False<br>1.<account>↔1.471418：True / True<br>82.98214819072565↔82.982148：True / True<br>-1.<account>↔-1.951594：True / True<br>15.23456↔15.2346：True / True |
| `run_all.py --dry-run`（本地伪造服务端） | 92 PASS，“全部通过”，rc=0 |
| `selfchecks/tb05_switches.py`（不带参数） | 36 passed / 0 failed / 1 skipped<br>跳过的是离线重放：缺省目录 results/ 不入库 |
| `tb05_switches.py <主工作区 results/run-20261101-190106>`（只读；只调 `rp.replay()`，不写文件） | 39 passed / 0 failed / 0 skipped<br>结果：收紧后 §16 不变；batch_as_of=ok（20260130=20260130）；“全程未尝试出网” PASS |
| 后端 ruff check / ruff format / mypy --strict（af589c0 上，内容包含本提交） | 全部通过<br>注：probes/ 不在 lint 门禁内（pyproject `extend-exclude`） |

## 核对

| 检查点 | 结论 | 依据 |
|---|---|---|
| 旧代码为什么错 | 旧代码取 `k=min(小数位)`。20.0↔19.6 时 k=0，`round(20.0,0)==round(19.6,0)` 为真，所以误判成精度差。 | f065f8d^ p11_gaps.py:242–255 |
| 新规则 | 三个条件同时满足才算精度差：<br>① 两个值的小数位数不同；<br>② 较短一方的位数 k 在 4 ≤ k ≤ 8 之间；<br>③ 较长一方按 k 位做 half-up、half-even 或向零截断，任一结果与较短一方的十进制值完全相等。<br>科学计数法的值记为 99 位，所以一律不算精度差。 | p11_gaps.py:87–88、259–285 |
| 反例被计为真实跳变 | 15.0→14.97 落在披露前，分类为 lookahead_suspected，precision_only=0 | 内置单测 p11_gaps.py:604–611，dry-run 和 tb05 中均 PASS |
| 其他调用方 | gap6-history 比对（p11_gaps.py:505–526）用的是同一个函数，所以同样被收紧 | 代码 |

## 问题

无 B，无 M。

- **m1（不阻塞，留给 T-B05 解读结果时注意）**：较短一方小于 4 位时一律算真实变化。例如 15.2345678↔15.23，新规则判 False。
  - 如果麦蕊某个字段本来就只给 2 位小数，这类变化会进 before_disclosure 或 unexplained，造成误报“前视嫌疑”。
  - 这是偏保守的方向，接受。
  - 要求：后端在 T-B05 回报里对 lookahead_suspected 逐条列出 from/to，由架构师人工排除这类 2 位截断。
- **m2**：tb05_switches.py:321 的缺省重放目录 results/run-20261101-190106 不入库，所以在 CI 或干净导出里这一项总是 SKIP。
  - 建议在 README 里写明：要验证这一项，必须带运行目录参数跑。

## CI

| 项 | 状态 | 负责人 |
|---|---|---|
| backend ruff / mypy | 预期绿：probes/ 不在门禁内，本提交改到的 selfchecks 本地通过 | 后端 |
| secret-scan | 跟随 3e5e288..2954b6c 一起推送（见总报告） | 运维 |

## 谁做什么

- **后端**：T-B05 回报里逐条列出 lookahead_suspected 的 from/to（m1）；README 补一句说明 m2。
- **测试**：无。
- **运维**：无。
