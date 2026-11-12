# B-05-consolidation｜六源收敛为五子资源入口
- 基线 main=`465e02046fa8d971897603742497444f884e89a2`；代码冻结=`2540f36cf3a7561fc15cca3ea11269053c0083ae`，后续仅本交付说明；独立 `ds/B-05-consolidated`，r2源码不变。

| 来源PR/终态 | 完整原提交 → 整合提交（缩写；每笔保留-x） |
|---|---|
| #51 `9af5b73` | `e30a07f→a7da225`、`9af5b73→09df32b` |
| #56 `5e63565` | `5e63565→4e3f89c` |
| #58 `bd85f06` | `bd85f06→54e99f2` |
| #59 `b8794af` | `45ba361→ecd8ff6`、`b8794af→3b08562` |
| #63 `3a14701` | `cef9de0→b1960ec`、`3a14701→a1978d4` |
| #71 `c7c9779` | `c7c9779→2540f36` |

- 完整9笔、33路径并集：32非冲突文件与各源终态blob相同；3处共用Python及5份夹具仅保留相同blob一份。唯一人工冲突为v1总入口两锚点，保留原注册并集四import/include各1；bars继续现有securities.router，search/profile不丢。
- 实际最终应用枚举：五GET及原search/profile均恰1次，OpenAPI五路径齐、重复operation警告0；来源与运行时审计JSON、原始日志在 `F:/workspace/team/status/B-05-consolidation-*`，RV-07报告在 `F:/workspace/team/reports/RV-07-route-registration-combinations.md`。
- 本地实际命令（cwd=src/backend）：`uv run --offline --no-sync pytest selfchecks/test_b03_seeds.py selfchecks/test_b04_bars.py selfchecks/test_b05_financials.py selfchecks/test_b05_fund_flows.py selfchecks/test_b05_announcements.py selfchecks/test_b05_factors.py -k 'b03 or b04 or b05' -q`：204 passed，1依赖弃用警告；含真实认证401/403/404、归属/伪造owner、fixture生产禁装、日历details及公告URL精确回归。
- 18受影响Python模块完整Ruff、6生产模块定向 `mypy --follow-imports=silent` 通过；实际路由枚举通过；`node --check`通过；B-03消费者dry实跑6非空类型/5真实mock形状通过，13空态类型仍被main旧string拒绝，未声称完整前端类型绿。
- 保留#59日历返修、#63链接规范化/逐条降级返修、#71可信空态投影；B-03非空factors仍仅合成输入/负例，未变成HTTP期望。#60契约与前端可空实现仍独立依赖，默认真实行情/财务/资金/公告/因子源未接入。
- CI未运行（计费）；完整PR范围双扫与diff检查结果见PR关键输出评论。仅内存SQLite/会话/合成夹具，无共享/生产库、真实样本、外呼、迁移、部署或main合并；不把历史单独绿数相加冒充本次组合结果。
- 源PR仅在整合Draft远端保存且来源审计确认后写明取代并关闭，保留分支；最终head/base及实际门禁命令以整合PR首行和评论为准。
申请新任务：继续r2原子发布交验；本单交Chief核验收敛入口并由复核检查实际整合，不另领第三项。
