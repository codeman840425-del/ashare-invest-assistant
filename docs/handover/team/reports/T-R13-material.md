# T-R13 ⑨素材（T-B59，供架构师代写docs）
- 依据：两遍p13原始响应、T-B58更正及 p13-signoff.md；本任务不改docs、不发外部消息。
- 逐个响应检查的字段与字符串统计：reports/T-B59-logs/v5h-fields.json；复用p13_analyze.currency_unit_fields，不再实现另一套识别。
- 已有样本：cashflow 600519/000001/601318；balance 600519/000001/601318；capital 600519/000001/601318/000550；另含更正公司及689009已有balance/capital。
- 已保存数值字段除空占位外无字符串；jzrq/plrq/bdrq仍是结构日期字符串，不应把它们描述为币种/单位元数据；全部已有样本未发现可信币种/单位字段。
- 对已有样本的结论：没有币种、单位字段，只靠数量级不连续检查；hbzj/yfbzj等原误命中已在T-B58修正。
- 尚缺T-R13规定范围：income四只600519.SH/000001.SZ/601318.SH/000550.SZ，balance与cashflow各000550.SZ；共6次，未自行调用。
- 仅在补齐上述样本并同样检查后，架构师才能在docs/mairui-verified.md⑨写完整范围结论并关闭V5h；现阶段不签收整个V5h。
