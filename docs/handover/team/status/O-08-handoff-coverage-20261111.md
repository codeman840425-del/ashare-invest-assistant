# O-08 issue #1 原交接条款覆盖核对

观察窗口：2026-11-11 北京时间20:49起；main=`465e02046fa8d971897603742497444f884e89a2`。依据为 [issue #1 原文](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1)、其评论及子issue #3–#7、当前全部PR列表（截至#71）。本单只核交付覆盖、当前head/状态和证据入口，没有重新评审代码、测试、试合或操作PR状态。**☑=交付证据已找到，◐=部分覆盖，☐=未核见完成证据；☑不代表已合入main或终验通过。**

## 原第21批四项（逐笔核对）

四个精确提交均由本地Git对象核验，`merge-base --is-ancestor <SHA> 465e020`均返回1，表明未进入本次已核main祖先。是否有等价补丁进入其他分支须单独查，不由祖先关系替代补丁等价性结论。

| 原条款/提交 | DS执行状态 | 当前入口与未覆盖项 | 下一责任人 |
|---|---|---|---|
| ◐ be/T-B134b `641cfd1fb8535f9ca37ffd72856677bee773e5af`，已完成不得重做 | [issue #5交付](https://github.com/codeman840425-del/ashare-invest-assistant/issues/5#issuecomment-6779066316)明确#25复用此父链 | [#25](https://github.com/codeman840425-del/ashare-invest-assistant/pull/25)为Draft、头`8ea3fb5`；当前PR列表未见该原分支独立入口；不能把#25替代完整原批验收 | 编排者/Grok确定原链纳入范围，后端给完整提交清单 |
| ☐ test/T-T77 `537c888fa45ae5af8b0e3114970bece995355c9e`，terminal无产品200、7/7 | 原文已有完成记录，DS未找到新的对应闭环回执 | 当前PR列表未见以test/T-T77为head的入口；[#24](https://github.com/codeman840425-del/ashare-invest-assistant/pull/24)仅历史冲突矩阵，不是该批合入 | 编排者/测试核远端归属与完整补丁入口，不重做原业务 |
| ☐ test/T-T78 `ffaf16703a9c54b67654f4201d4d827550eebc35`，可卖/快照连库29/29 | 原文已有完成记录，DS未找到新的对应闭环回执 | 当前PR列表未见以test/T-T78为head的入口；不能用#25作者64定点替代原连库批 | 编排者/测试确认必要原测试如何纳入并绑定验收SHA |
| ☑ docs/T-R58 `6814edc61ac85db3464d793a28df73191cc7df7e`，方案先行 | [#20](https://github.com/codeman840425-del/ashare-invest-assistant/pull/20)已承载后续方案，当前头`f3bcfbd`、Open未合入；[#8](https://github.com/codeman840425-del/ashare-invest-assistant/pull/8)复审`6b250a2`已交 | 合当前最新方案头而非只取旧6814edc；保留P9补充，#8/#10依赖随后核 | Grok审定合入，架构师维护方案身份 |

## 原任务队列与验收条款

| 原条款 | DS覆盖/可核入口 | 尚未覆盖或不能销项的部分 |
|---|---|---|
| ☑ P0 T-A148d复审§2.7/§7、容差裁定 | #8 `6b250a2`＋[A150预审](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6778577424) | 已交复审不等于参数容差获得实盘验证；方案#20仍待合 |
| ◐ P0 T-B136实现、34组+R组、可复现与门禁 | [RV-23路线](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6789797307)定位主线`d4405a8`与#28/#29；[RV-01](https://github.com/codeman840425-del/ashare-invest-assistant/issues/3#issuecomment-6790812733)只复算固定checkpoint子集 | r2未收到全量冻结通知；三件套/全trial账、敏感性、保留集、R/P5与复现总包仍待终核，不据进度估算判完成 |
| ◐ HF/TDX/vipdoc来源与哈希门禁 | [issue #3后续输入指令](https://github.com/codeman840425-del/ashare-invest-assistant/issues/3#issuecomment-6777783330)明确公开下载、固定HF revision、只读本机lc1；[RV-01清单](https://github.com/codeman840425-del/ashare-invest-assistant/issues/3#issuecomment-6790453422)列冻结要求 | 最终执行adapter/输入/配置/输出摘要与实际r2运行身份绑定仍须后端交；本单未重新读真实输入或验证数据包 |
| ◐ 主跑佣金/两敏感性、S3/S7/ST/印花税/前视/保留集纪律 | #20方案＋#28 `a782a1e`输入/P9补充＋[#10](https://github.com/codeman840425-del/ashare-invest-assistant/pull/10) `3ea69b6`框架/1bp勘误 | 声明/代码已在不等于本轮数值通过；完整费用、因果性、锁历史及P1–P10由复核→测试→研究接续；禁止重开保留集补证 |
| ◐ T-T81拼接接线、去恒真断言 | [RV02](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6791590691)冻结#15=`41c58e4`复现15过9跳、#26=`9beee6e`接线25+38过 | #15/#26等价已入主线候选，须明确替代入口后再关闭；#26不同base/34提交不能机械合；T-T84及独立回归完整父链仍按RV-23收齐 |
| ◐ T-DATA-ST来源/许可、覆盖率、10只核对 | [#9](https://github.com/codeman840425-del/ashare-invest-assistant/pull/9) `497a117`；[issue #4交付](https://github.com/codeman840425-del/ashare-invest-assistant/issues/4#issuecomment-6777524555)：深市转换/8只核对已交 | 原10只中沪市2只生效日未闭环、沪深manifest总覆盖与许可限制仍留缺口；#28/#29状态输入/12只旁证不能自动替代原10只及许可验收 |
| ☑ T-B134c缺可卖归零/过期gap、先红后绿 | #25 `8ea3fb5`；[issue #5](https://github.com/codeman840425-del/ashare-invest-assistant/issues/5#issuecomment-6779066316)作者64定点/3权限负例及回退负控；[RV20](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6780618819)静态通过有限定 | 仍Draft/未合入，日志身份限定保留；原排程“复测先完成”未因提前实现被本单重新裁定 |
| ◐ T-T80恢复xfail、三段一致、坏配置真红 | #11头仍`7787441`；严格修复现已推为[#48](https://github.com/codeman840425-del/ashare-invest-assistant/pull/48) `2c8c1af`（代码e0d11eb） | 不再称修复仅本地，但#11旧头仍有负控缺口；#48如何吸收/替代由合入者定，#11/#37合入后的三段注释联核未执行 |
| ☑ S10 data_source注释旧口径 | [#37](https://github.com/codeman840425-del/ashare-invest-assistant/pull/37) `47f5ae7`；[补核](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6791601690)/[正文勘误](https://github.com/codeman840425-del/ashare-invest-assistant/pull/37#issuecomment-6791568025) | 净增量通过限定保留，46过/13跳/3XFAIL/1既有败、config/plan/快照3/3/2；跨PR三段对齐待合入后核 |
| ☑ T-O77 mypy7项/notification_ref_type | [#14](https://github.com/codeman840425-del/ashare-invest-assistant/pull/14) `a199900`；[issue #7](https://github.com/codeman840425-del/ashare-invest-assistant/issues/7#issuecomment-6777831077)记录修复/自检 | 已交付未合入；隔离PG缺失不冒充测试通过；#25重复登记已去，契约行只留#14；后续ruff归因#37不是旧快照全量修绿 |
| ☑ 判读/复核/部署接手文档 | [#47](https://github.com/codeman840425-del/ashare-invest-assistant/pull/47)合成预演、[#69](https://github.com/codeman840425-del/ashare-invest-assistant/pull/69)首轮样张、[#52](https://github.com/codeman840425-del/ashare-invest-assistant/pull/52)重启预案、[#64](https://github.com/codeman840425-del/ashare-invest-assistant/pull/64)部署链 | 首轮170trial/0腿和data_insufficient不代r2；部署/宿主重启待当次执行令，不将文档交付视作执行 |

## 流程与红线（证据和限制分开）

| 原条款 | 可核情况 | 移交限制 |
|---|---|---|
| ◐ 只走任务分支PR，由Grok审合；不推main/不强推 | 当前列表全部已查PR均未merged，main仍465e020；四笔原批也均非其祖先 | 不据本次快照追认全部历史操作；团队其他裁定不自动修改本次main合入权 |
| ◐ 提交前全部要求的扫描/mypy/迁移头/checker两模式/build | [A-10预审](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6795970880)区分齐全/保留/缺声明；[O-04 #44](https://github.com/codeman840425-del/ashare-invest-assistant/pull/44)固定双扫流程 | 工具可用不等于各旧PR已补扫；A-11/T-08补声明与定点证据仍按本人新回执销项，本单不复跑全量或替CI盖章 |
| ☑ 每单评论/分支hash/待裁定项 | issue #1/#3–#7及当前PR构成证据索引；[O-05旧窗口快照](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6792068365)仍保留历史用途 | O-05的36个Open仅17:08–17:16窗口，不能再当最新总数；本单是原条款核对，不是新PR全队列终审 |
| ◐ 共用仓库不stash、不同任务分树 | 本单独立ds/O-08、主树他人WIP未碰；[工作树规则](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6777960454)已立 | 未审计全队全部历史命令；仍有旧根目录工作树待各所有者按保护WIP/证据原则迁移或清理，本单不删除 |
| ◐ 禁密钥/私样本/真实麦蕊/正式库写入/部署/信号发布 | 原issue红线保持；各交付有范围声明，O-08只读Git/API与文档；[历史T-O79](https://github.com/codeman840425-del/ashare-invest-assistant/issues/1#issuecomment-6779557578)另有本人授权记录 | 不能把后续单独授权当作本次通用权限；未对全宿主网络/数据库历史做独立审计，不声明所有历史行为已验证零调用 |

## 未覆盖项与恢复评审后的建议顺序

1. **原第21批T-T77/T-T78入口**尚未核见，B134b借#25复用但完整纳入范围待定；编排者组织提交清单交Grok，不重做原功能或机械重合。
2. **主线ds/T-B136→main集成入口**在本次截至#71列表仍未见；A-11已挂，须收齐RV-23所列测试父链和必要增量。#28/#29/#36依赖该父链，不以单个子PR代替主线交付。
3. **r2完整结果**未收到冻结回执，不放行。后端冻结/持久归档→复核终算→测试R1–R5→研究员T-R66/R67；B-01两列只面向下一版，不能倒填本轮R证据。
4. **#48/#11/#37联核与#17新版执行单**未闭环，准确绑定远端SHA后再决定替代/合入；#11旧说明不能当负控已修。
5. **ST原验收缺口**继续留issue #4：沪市2只、生效日期、覆盖分母与许可；输入状态升级须有依据，正文旁证不自动改termination分类。
6. **门禁声明/集成冲突**按A-11/T-08收口；新五路由共同注册锚点冲突、#35/#38看板冲突交合入者保留全部必要内容并定点验证。#63新增URL安全问题正在RV-04审，不能因作者35项通过宣布其可合。
7. **新增P2N能力仍只到空态/fixture**：#56/#58/#59/#63/#71不等于生产数据源就绪；前端#19/#54待合触发项和#68/#70消费对齐继续跟踪；B-06保持原门槛，不在本单加授权。

DeepSeek 行：未用；交接实况与证据适用范围不外包。
申请新任务：本单收口后按池领取O-09只读资源盘点；r2冻结归档协助优先。
