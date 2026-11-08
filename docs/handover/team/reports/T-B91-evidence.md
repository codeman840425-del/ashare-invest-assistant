# T-B91 定点证据（全部合成、隔离）
38个唯一用例分组：条件14；连续性4；资金日报5；旧档只读1；P1六维最早值1；RC1实际队列1；草案确认1；回滚/并发/操作数/鲜度/收盘8；混合成本最早时点1；原角色1；操作数结构1。
日志位于本机：/tmp/tb91-conditions.log；/tmp/tb91-reports-rc1-drafts.log（前10项）；/tmp/tb91-last7.log（前2项）；/tmp/tb91-draft7.log（首项）；/tmp/tb91-left8.log（8通过）；/tmp/tb91-last2b.log（RC1通过，后续socket断言已修）；/tmp/tb91-role-final.log（最终角色通过）；/tmp/tb91-mixed.log（混合时点通过）。
早期失败为合成夹具缺止损/重复市场有效日、socket编码断言，以及真实发现的同刻新旧建议混选；均已修，RC1查询按实例当前版本绑定。
生产边界：报价入口接受可信采集完成回调，未启动采集器/beat；所有账户、身份、行情、卡、通知均虚构；真实用户与资金无操作。
B1需架构师明确buy/add本笔最大亏损输入字段/来源/单位/时点，以及剩余实例预算已使用额度归属；未将缺项设0或任意复用其他预算。

## T-B91收尾 38fc560cdc3fb2efe8853d3ad545396754c558da
前文B1“待架构师”由T-A40解除，已实现，不再等待。
最终13节点分组证据：/tmp/tb91-close-final2.log（10过）；/tmp/tb91-close-legacy-root.log（2过，含新增旧档正投影与旧档无源）；/tmp/tb91-close-assets.log（1过，资产未知）。
最终受影响复验：/tmp/tb91-close-draft-operands-final.log（多实例/输入金额fallback/越价预算）；/tmp/tb91-close-price-budget.log（价×量不可绕预算）；/tmp/tb91-close-no-stop-final.log（改为真实无止损候选）；/tmp/tb91-close-legacy-final.log（旧档PIT保护）。均0失败；早期失败日志保留但不作为最终验收。
10a冻结1ba4313不含f28727d，git祖先核验exit1；只读d34e1b0断言按market/account/stocks/dimensions已知时点取min，未复制其tests进业务目录或篡改断言。旧档修复只读，不重写冻结事实。
DeepSeek只复用原已审核操作数(12.34×100为完全虚构金额输入)，并非预期答案；API/DB查询与Decimal断言本地。
