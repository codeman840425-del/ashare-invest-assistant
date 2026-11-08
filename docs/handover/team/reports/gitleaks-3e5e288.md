# gitleaks --all：3e5e288 tb46x.py 命中核实与豁免（运维，2026-11-01 20:1x MST）

## 结论
- **4 处命中全部是虚构值**，已按指纹登记在 `.gitleaksignore`，提交 **`2954b6c`**（只改 `.gitleaksignore`，用 `--only` 提交，未推送）。
- 历史没有改写，`.gitleaks.toml` 也没改。

## 命中（gitleaks 8.30.1，`scripts/ci/gitleaks_run.sh history`，对全部历史）
| 提交 | 文件 | 规则 | 行 | 处数 |
|---|---|---|---|---|
| 3e5e288 | src/backend/selfchecks/tb46x.py | S5-sh-holder-code | 336 | 2（同一指纹） |
| 3e5e288 | 同上 | 同上 | 353 | 1 |
| 3e5e288 | 同上 | 同上 | 372 | 1 |

指纹格式为 commit:file:rule:line。336 行的两处命中指纹相同，所以 4 处命中只对应 **3 条** `.gitleaksignore` 记录。

## 核实方式（全程不输出号码，号码只在内存里比对）
1. 用脚本按 `.gitleaks.toml` 里的 S5 正则，从 `git show 3e5e288:…` 取出这 3 行的匹配值。脚本只输出特征：长度、前缀是否字母、是否在白名单、是否全零、不同数字个数、是否连续递增。
2. 结果：4 处是**同一个值**，形如 “A + 9 位连续递增数字”，是明显的顺序占位模式。它不在已知假代码白名单（<account>/<account>/0000000001/0000000000）里，但同样属于明显的占位写法。
3. 上下文（数字已掩码后查看）：这些值只出现在日志脱敏自检的断言字符串里，例如 `check("A######### not in redact(...)", "<account-field>脱敏")` 和 `raise RuntimeError("证券代码 A######### …")`。用途是验证 redact() 会把它脱敏，不是业务数据。
4. b3aab3c 的提交说明写明“虚构<account-field>/<account-field>改为运行时拼接（修正 3e5e288）”。核对结果：b3aab3c 和当前 HEAD 都不再含该字面量，且 b3aab3c 是 HEAD 的祖先。
5. 参照 reports/T-T25.md §8.3（测试那边已判定为虚构<account-field>）。
6. 没有调用麦蕊。

## 复扫（2954b6c）
- gitleaks `--all`（242 个提交）：**0 findings**。
- secret_scan：history 阻断 0；tree 阻断 0；range 2954b6c~1..2954b6c 阻断 0、警告 0。
  - history/tree 的 9 条警告是既有的告警级 S8/S9，分别在 dryrun_mock.py 和 frontend dist，与本项无关。
- check_real_secrets.sh：worktree 和 range 都为 0。
- scripts/ci/tests 中与 gitleaks、secret_scan 相关的用例：202 passed。

## 待复审
- `.gitleaksignore` 的新增内容按文件头约定，须架构师或测试负责人评审（CODEOWNERS）。

## 追加（20:2x MST）：reports/T-O01.md:116、T-O01a.md:183 的 generic-api-key
- **结论：不是密钥。** 两处是同一个 21 字符的值，都是我们早先在报告里引用的“gitleaks 误报”原文：表结构文档里 jsonb 示例 `key:"…"` 的行情字段路径（plan 字段路径）。在仓库里，它以 `evidence_key` 允许样例出现在 scripts/ci/tests/cases.py:128。
- **核实方式（不输出值）**：
  - 看长度、字段名和上下文：它出现在“误报”说明文字里，字段名是 key，内容是字段路径。
  - 在内存中比对 63 个候选：<path> 下的文件、主仓和部署克隆 deploy/env/.env 里的各个值、MAIRUI_LICENCE / DEEPSEEK_API_KEY 环境变量（只读，没有修改）。比对方式是互相包含，结果 **0 命中**。
- **处理**：两处都改成 `key:"<REDACTED-EXAMPLE>"`。reports 目录不在 git 仓库里，所以没有提交。
- **git log -S**：主仓 `--all` 命中 3 个提交，都已在 origin/main（已推送）。命中内容是 plan 和 CI 用例里的同一个字段路径，不是密钥，不需要处理，也不需要轮换。
- **复扫**：对这两份文件跑 gitleaks dir，0 findings；对整个 /workspace/team/reports 目录，0 findings。
