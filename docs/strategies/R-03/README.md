# R-03｜r2 判读空槽与合成填充预演

本目录把 R-02 发布模板落实为可填的 Markdown 骨架，服务私聊 T-R66 出数判读。群聊本单只用合成展示值，不读取在写的 r2 checkpoint 或正式三件套。工具只复制读数和原状态，不计算统计量、P1–P10 或放行结论。模式、复核状态与缺证始终可见。

## 固定依据

- [R-02/T-R59 判读框架 §7](https://github.com/codeman840425-del/ashare-invest-assistant/blob/3ea69b65a31d7c8488c0bb6babdec6e6312d2863/docs/strategies/T-R58/judging_framework.md)：窗口表、证据、红旗和用户发布措辞；§2 含 RV-01 的 +2bp/−1bp 净收益勘误。
- [T-R68 P1–P10 字段映射](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a1776a139ad99903bbaf243652667dd6bec2459c/docs/strategies/T-R59/p1_p10_field_map.md)及[原预筛工具](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a1776a139ad99903bbaf243652667dd6bec2459c/docs/strategies/T-R59/prescreen.py)：精确路径和自动/人工检查边界；本单不改预筛工具。
- [T-R58 方案](https://github.com/codeman840425-del/ashare-invest-assistant/blob/6814edc61ac85db3464d793a28df73191cc7df7e/docs/strategies/T-R58/retest_plan.md) §8.3/§9，以及当次冻结版本和后续生效裁定：正式判据来源；框架推导量级不升级为门。
- [T-R66b 公告正文交叉核](https://github.com/codeman840425-del/ashare-invest-assistant/blob/35dfe61e2258006c543b0fbe98135207ae2884d8/docs/strategies/T-R66b/README.md)：实际是 P9 的公告证据，非独立统计框架。公告核对不等于本次运行时退市检查通过，也不自动升级分类。

本分支从 `origin/main@465e020` 独立创建，仅新增本目录与交付记录；以上待审文档未复制进本分支，不引入其上游代码。正式使用前核对冻结版本，不把来源链接等同依赖已合入。

## 产物和离线用法

- [report_template.md](report_template.md)：五窗口、P1–P10、R0–R14 和七项附表的空槽；所有缺值显式显示缺证。
- [render_report.py](render_report.py)：标准库填充工具；缺省渲染空槽，`--write-blank` 生成可编辑 JSON 输入。
- [rehearsal_check.py](rehearsal_check.py)：仅运行本文合成 oracle 的定点检查，不连接外部服务或执行策略。
- [synthetic_input.json](synthetic_input.json)及[synthetic_filled.md](synthetic_filled.md)：合成填充示范。n、均值、区间为手工给定展示值，未从交易腿估计，未运行策略/显著性检验；三件套 SHA 槽故意保留 null。

在仓库根目录执行，输出使用自己的新文件或仓库外状态目录：

```powershell
python docs/strategies/R-03/render_report.py --out report-empty.md
python docs/strategies/R-03/render_report.py --write-blank --out report-input.json
python docs/strategies/R-03/render_report.py --input docs/strategies/R-03/synthetic_input.json --out report-synthetic.md
# 正式出数后的私聊 T-R66：核对原产物，填写 report-input.json，再渲染草稿
python docs/strategies/R-03/render_report.py --input report-input.json --out report-draft.md
```

`mode` 只能是 `not_executed`、`synthetic`、`checkpoint`、`formal`。输入可只覆盖已知槽，未提供项保持 null。未知键拒绝，防止拼错字段静默漏填。数值以原始十进制精度显示；不将阈值附近值四舍五入后判定。`--out` 不得覆盖 `--input` 或已登记的三件套路径，也不得使用三件套原文件名。工具不读取、核验三件套本体或自动适配原 schema，SHA 由 T-R66 先核验后登记；输入 SHA 仅校验归一化输入的留存版本。工具不访问网络、数据库或 runner，也不会根据草稿调用发布接口。

## 三件套到位后的填充顺序（私聊 T-R66）

1. 后端声明完整产物已冻结后，登记 run_id、代码/方案 SHA、结果截止北京时间、全量或指定子集范围；分别核对三件套 SHA256。缺件、仍在写或快照不一致时保留缺证。归一化输入的 SHA 由渲染器另算，不能代替三件套 SHA。
2. 沿 T-R68 做已有的 10 分钟红旗预筛，核对自动检查的证据覆盖；`clear` 仅指该冻结范围完成的检查，不把自动检查子集扩为红旗全绿。未执行/不可自动判的项留黄色，结构疑点留红色并报后端。
3. 按下表从原产物复制读数，填写窗口和判据槽。必须按 phase/candidate 明确关联；不猜窗口数组位置，不用推导值代替实测。每行至少给三件套 SHA 的登记项和 JSON 路径或 CSV trial_id/筛选条件。
4. 单列 P9 公告证据、运行时退市四分类与残余风险；单列 R 汇总计数、反推量和逐腿缺证。独立复核报告到位才登记 completed，工具要求同时给证据位置。
5. 渲染后检查首页/窗口/红旗/附表；由 T-R66 研究员给最终判读，编排者统一发布。工具始终输出草稿，不因输入 `pass` 或复核 completed 自行给出“已通过/已放行”。

| 输入槽 | 原产物/填入依据 | 必须保留的限制 |
|---|---|---|
| `windows.evaluation_1…4` | P1 各窗口与 `trials` 的 `evaluation_i/selected_A` 对齐；n/days/mean/low/high | 核对候选与 phase；缺身份先缺证，不能按数组序号猜 |
| `windows.holdout` | P1 保留集、`trials` 的 `holdout/selected_A`；成本取 P3.average_cost_bp | 同一候选与范围；其他窗口成本未输出就留 null |
| `criteria.P1…P10.status` | 原 `criteria.Pn.status` | pass/fail/unknown/unverifiable 原样保留；缺键/null 显示缺证 |
| `criteria.Pn.observation/evidence/gap` | T-R68 每条路径；三件套 SHA + JSON 路径/trial_id | P4 用并集；P5 单看 paired.n 不能证明逐腿 1:1；P8 是原方案观察用途 |
| `flags.R0…R14` | R-02 §4、T-R68 §2、预筛和人工证据 | pending/insufficient/clear/hit/confirmed 分列；已核标记必须给证据 |
| `annex.r_control` | P5.paired、A* n/均值、是否存在等价逐腿对照字段 | 反推写“推算”；两列在后续 B-01 存在，不代表冻结 r2 已落盘 |
| `annex.p9_crosscheck` | 原 delisting + T-A155 生效版本 + T-R66b 正文证据清单 | 不改 termination_list；证据升级须正式裁定，不用正文核对替代尾段核验 |
| `annex.coverage/splice/cost_components/sensitivity` | 覆盖/剔除分母、拼接分段、费用五项、敏感性原档 | 元、bp、% 分列；佣金最低值逐腿核对，1bp 推导不能填作观测 |

其余附表槽 `remaining` 必须写缺什么、谁补和下一步。复核为 pending 时，即使原判据全部 pass 也保持呈现草稿。0 腿窗口显示 `n=0` 和“均值/区间不可估”，不据 `0.00bp` 或 `p=1` 归因策略无效。源状态与展示提示分列，不改源产物。

## 合成演练 oracle

合成输入故意将保留集放在 JSON 的第一项，仍须按 phase 填在第五行；evaluation_2 注入零样本但统计量给 0，输出须显示不可估；evaluation_4 完全缺失，n 不得补 0；evaluation_3 缺成本，不得借保留集的 35。保留集 `69.99997` 必须保留全部位数；P1 原 fail 不重算，P8 unknown 不升门。

红旗 R0 为合成注入的 L8 失败疑点，必须呈红色“疑点/暂停判定”，不写已确认缺陷；R13 为逐腿对照缺证，必须呈黄色；其余未执行不能呈绿。无证据的 clear、无复核报告的 completed、未知 phase、负样本数、非有限数值和倒置区间应拒绝。演练只验证填写/呈现/缺证边界，不验证策略或 runner。定点复现命令：

```powershell
python -X utf8 docs/strategies/R-03/rehearsal_check.py
```

DeepSeek：未用；本会话环境及共享密钥目录均无可用 DeepSeek 凭据，未发起调用。判读与缺证 oracle 由研究员制定；模板空槽和产物由本地确定性代码生成并逐项核验，未将规则或结论外包。

申请新任务：正式三件套冻结后由私聊 T-R66 填数判读；本群交付后按池续领研究单。
