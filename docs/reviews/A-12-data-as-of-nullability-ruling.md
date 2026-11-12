# A-12 终裁：DataStatusBlock 全站可空与 SSE quote 推送前提

日期：2026-11-11（北京时间）。依据：编排者在 PR #78 评论 6797263288 的终裁、RV-06 事实备忘录、PR #72 非 SSE 增量；取代本文件初版的证书为空即清空 profile 时点、快照块一律非空及「无数据不推是既有实现事实」三处表述。#72 已关闭，由 #78 唯一承载相关契约增量。

## 1. 取证与适用范围

共同基线 main=465e020。直接核读 `app/master/profile.py:34–42,71–101`：公开字段带原始 master_as_of，profile 当前仍固定 data_as_of=null；本终裁是待实现的规则，不能声称基线已符合。直接核读 `app/notify/transport.py:35–83`、`app/api/v1/notifications.py:162–231`：transport 序列化/重放原 payload，未校验 quote.items/data_as_of；/stream 做会话校验和心跳、不构造行情块。自检 `test_tb92_repairs.py:554–608` 的 quote 仅 synthetic_index，用于会话撤销，不能证明生产 quote 非空保证。前端 streamTypes 的 quote.data_as_of 和 Evidence 当前均非空。

## 2. DataStatusBlock：键必有，值可空，全站统一

`data_as_of: string(datetime) | null` = 本响应实际使用数据时点中最早的非空值；并集全空才 null，不用生成、评估、当前或心跳时刻代替。只在实际返回内容的时间集合上求值；旧数据仍保留旧时点，部分缺失不抹掉已有时点。T-A53、日报与风控评价的最早非空规则在此全站外延，不能据外延改变已有接口路由、错误码或存储约束。

- SecurityProfile：并集为公开主数据与本人证书参与字段各自的可信时点。公开侧使用 master_as_of 快照日对应的原始带时区时间戳（现存 securities.master_as_of），证书侧使用实际数据时点，只有采集时点可得时用对应 fetched_at。date 型 master_as_of 本身不凭空变成零点/当前 datetime；若原始时点确缺，保留日期、以 gaps 披露缺口，只在可证明的非空时点上取最早值。公开时点存在时，即便行业/股本等证书字段全空也不能返回 null；data_status 按 §1.1 仍为 partial。主数据首导前置与 master_as_of 必填不变。
- SectorFlowsResponse：无任何可用板块流量时 data_as_of=null；有数据取实际参与行的数据时点最早值。本次只裁 data_as_of，不连带修改 trade_date 的日期契约。
- MarketOverview：参与输入时点全空则 null；有任一可用时点则取最早。顶层 trade_date 保持既有定义，不能用日历日期填充行情 data_as_of。
- CandidateSignal 等对象如有 DataStatusBlock，仅该块服从总则；独立 at/created_at、snapshot_id 和 Evidence 的值域不受外延影响。SignalEvent 的契约结构未声明顶层 data_as_of，不新增该字段。
- Evidence：data_as_of/fetched_at 按既有单条证据定义非空；value=null 不意味着可删时间锚点，也不能拿当前时刻伪造其历史时点。缺少可信锚点的证据不能靠本裁定放行。

## 3. SSE quote：契约规定推送前提，data_as_of 维持非空

终裁规定：无 quote 变化不发布新的 quote 事件；发布块 items 至少一条有可信行情时点的变化项，顶层 data_as_of 必须出现且为非空 datetime，取该块实际行情时点最早值。无可发布项时不得制造空 quote，也不得以 publish/heartbeat 时刻补值。HTTP /quotes 的逐项 DataStatusBlock 与 SSE quote 顶层是不同结构。

这是补入契约 §8 的明确规范，**不是基线已实现的行为事实**。当前通用 transport 不代做该校验；后端后续生产发布接线必须在业务发布入口落实。续传仍重放合法历史事件，不因当前行情未变化抑制既有合规历史块；心跳/reset 机制不受影响。

## 4. 权限、兼容性、迁移与受影响任务

本人证书数据隔离、仅本人自选/持仓 SSE 范围、401/403/404、会话撤销、CSRF、ETag、审计与幂等规则均按原契约，本单没有新增写接口/审计事件/迁移。禁止以他人证书或其他用户缓存补时点，禁止靠 owner 变体扩权。

兼容性：必填 datetime 放宽为 datetime|null 对旧的非空消费代码可能不兼容，须同步前端类型和空态展示；不能宣称旧客户端无影响。返回键仍不可省略，历史非空值不回填、不重写快照。SSE/Evidence 维持非空，对未来生产发布端增加明确验收前提。

- 前端 F-14：SecurityProfile/SectorFlowsResponse/MarketOverview 三处落型；全局 DataStatusBlock 外延按总则核对继承消费，不把 Evidence/StreamEventMap.quote 放宽。与 #70、T-A158/#60 组合时保留各自增量。
- 后端：profile 不再仅因本人证书为空而固定 null；其他响应块核对最早非空算法。quote 生产接线专项落实 §8 前提，不能以 transport 自检替代；实现另派，不在本单修改。
- 测试：按下列定点集覆盖；不使用真实数据或共享库。plan §3.1、契约 §1.1/§5.1/§8 与本文同步。

## 5. 可执行验收与负例

1. 全空/一非空/多非空/旧缓存分别得到 null/该时点/最早值/原旧时点；禁止缺键、生成时刻补值及一处 gap 清空全部时点。
2. profile 仅公开时点非空→该时点，证书更早→证书时点，公开更早→公开时点；仅 date 缺原始 timestamp→不构造 datetime、披露缺口。ETF/指数与普通证券同算法。
3. SSE 新事件：无变化、空变化集、无可信行情时点→不发布 quote；合法变化→非空 data_as_of；部分行情缺失不得伪造补齐；合法历史块可按续传重放。
4. 权限负例：未登录/未批准仍为既有401/403；跨用户本人资源仍404；公开资料可读不授予他人证书字段，SSE 会话撤销后不再发帧。此次仅静态核对路由与 live() 检查，动态权限负例待实现方用隔离合成环境执行，未冒称通过。
5. Evidence 的 null value 不放宽其时点；前端三处 null 正常展示，Evidence/SSE 仍拒绝 null；不重写历史快照。

DeepSeek：未用，原因：裁定不外包。
申请新任务：A-11 合入潮收口继续；F-14 与后端接线由编排者派单。
