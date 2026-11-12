# O-CI1-PROFILE-CONTRACT：因子空集版本可空性

依据：2026-11-12 Chief 明确裁定；冻结基线 `776a011b06a5d7427969e7977868995593b12bcf`。本次只同步文档，后端 PROFILE 与前端 PROFILE-NULL 负责下一批实现，运维统一发布。

既有定义：契约 §7.3 原字段为 `factor_set_version: string`，ETF 已规定空 items/total 0/unavailable/not_applicable；plan §3.3 的 `market.factor_values.calc_version` 与 §2.5.14 的 `feature_set_version` 均不能证明本接口已注册因子集版本。冻结基线没有四数据集正式 GET 实现；后端 WIP 的适用性空响应没有可核实的因子集版本，前端 `FactorsResponse` 仍按必字符串处理。空串、示例串及 APP_VERSION 会伪造版本身份，不采用。

`factor_set_version` 字段保持必出现，改为 `string | null`；只针对 `/securities/{code}/factors` 顶层，不改变每个因子 value 的可空性或其他版本字段。

| 场景 | 版本与验收 |
|---|---|
| 本版 ETF | 必为 null；items=[]、counts={total:0, by_category:{}}、unavailable，factors/not_applicable |
| 明确无可用真实因子集/无来源 | null；同空集/unavailable，factors/no_source，不伪造发布时间或任务 |
| 本人证书不可用且无可用真实因子集 | null；同空集/unavailable，factors/data_licence_unavailable，不借他人证书或无归属行情行 |
| 有适用且可核实的真实因子集 | 真实非空 string；与所返回因子集绑定，不取应用/示例版本 |
| 有已知真实因子集，仅分类/日期筛选后为空 | 保留该真实 string，不按 items 长度抹成 null |
| 非空因子数据却缺版本绑定 | 完整性阻断；不得用 null 和正常数据状态交付，也不得静默丢数据伪造无源空集；修复真实绑定 |
| 空串、字面字符串 null、APP_VERSION、其他人的版本 | 拒绝作为本接口版本；不得为通过类型断言虚构注册记录 |

适用证券及 gap 仍按原类型/本人证书事实判定，不把运行错误、未知代码或权限失败转换为 ETF 例外。原 401/403/404/400、弱 ETag/304 与 private-no-store 保持；读接口不新增写入、抓取、审计或状态跃迁，不要求幂等键。完全无数据时 data_as_of=null，不用当前时间补齐。

并存/兼容：正常 string 分支保留；限定空集首次允许 null，旧客户端严格 string 假设不兼容，后端 schema/新增类型断言、前端类型/mock/空版本显示须与这份契约同批。前端 null 不展示“因子集 null”或虚构版本；非空真实版本原样显示。没有数据库或历史数据迁移，不回写旧记录，不改变 calc_version/feature_set_version。

验收由属主定点执行：ETF完整空集；无源与本人证书不可用各自 gap；真实版本正常展示与筛选空集仍保版本；非空数据/null、空串/应用版本不能被接受；跨用户来源不得补齐；原 test_07 全部断言以及匿名/未审批/未知码、ETag/cache 权限负例保持。本文静态同步不代替实现、DB或当前 GitHub CI 结果。

取舍：采用显式 null 表示没有真实因子集身份，保留证据缺口；没有引入 unversioned 字符串、假注册表、自动抓取或省略字段。契约 §7.3 与 plan §3.3 已同步；实现未具备真实因子集时不能据此宣称正常因子 provider 已接线。

DeepSeek：未用，原因：契约裁定与同步不外包。

申请新任务：后端 PROFILE、前端 PROFILE-NULL 按以上真值分支交定点证据；运维纳下一批 PR89，以该头真实 CI 为准；LOCAL-ID 保持暂停。
