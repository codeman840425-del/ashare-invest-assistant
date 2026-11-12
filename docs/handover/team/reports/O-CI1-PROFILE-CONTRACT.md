# O-CI1-PROFILE-CONTRACT

- 基线：776a011b06a5d7427969e7977868995593b12bcf；自有 ds/O-CI1-PROFILE-CONTRACT，仅 docs，不修改已发布头或 LOCAL-ID。
- 依据：2026-11-12 Chief 裁定；[契约 §7.3](../../../api-contract.md)与[plan §3.3](../../../plan.md)同步；[详细裁定与验收](../../../reviews/O-CI1-PROFILE-CONTRACT.md)。
- 字段必出现 string/null；ETF 无适用集必 null；无可用真实因子集的空响应为 unavailable+实际 gap，不造版本/时点。
- 有真实因子集保真实非空版本；筛选空集不抹版本，非空数据/版本缺失不能冒正常结果，不吞权限/SQL异常。
- 不兼容点：旧客户端/schema/mock/测试的必字符串假设；后端 PROFILE 与前端 PROFILE-NULL 同步下一批，正常字符串分支保留。
- 后端须保持原 test_07 及权限/ETag负例，补空集/真实版本/筛选空集不抹版本反证；前端 null 不展示、真实版本照常，属主按各自单交实绩。
- 本单仅静态核文档结构/相对链接及冻结源码定义，不启动服务、不代跑数据库/业务/全量；本单不宣称实现或 GitHub CI 绿。
- 无数据库/历史记录迁移，GET 不新增写入/抓取/审计；原本人证书隔离、错误码与缓存规则保留。
- DeepSeek：未用，原因：契约裁定与同步不外包。

申请新任务：运维把本 docs 提交纳 PROFILE 下一批 PR89，合并后观察真实 CI；后端/前端按 Chief 已派范围续作，LOCAL-ID 仍暂停。
