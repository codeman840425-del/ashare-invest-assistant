# T-R16 2026 交易日历（策略研究员，2026-11-07）
交付（仓库内，未提交，待架构师代提交，逐文件暂存）：
 docs/strategies/calendar/trading_calendar_2026.json（后端复制为 config/trading_calendar.json；本任务未改 config）
 docs/strategies/calendar/trading_calendar_2026_sources.md（来源与逐假期核对）
 docs/strategies/calendar/build_trading_calendar_2026.py（生成与断言）
格式：{coverage_start: 2026-01-01, coverage_end: 2026-12-31, open_days[242], source}，与 financial_basis.TradingCalendar / 契约 §7.2 第 2 条一致；不外推 2027 年。
来源：上交所 上证公告〔2025〕45号（2025-12-22）<url>
      深交所 深证会〔2025〕481号（2025-12-22）<url>
沪深一致：7 个假期的休市区间、复市日和点名的周末休市逐字一致，所以只出一份日历。
校验：断言 open_days 中没有周末，调休周末 6 天都不在其中，7 个休市区间内没有开市日，复市日都是区间后的首个开市日，列表已排序去重；按 261 个工作日 − 19 个休市工作日手算为 242，与生成结果一致；用后端 load_calendar 加载成功，next_day(2026-09-30)=2026-10-08，next_day(2026-12-31)=None（超出范围不猜）。
残余：上交所单项休市公告只核对了标题；深交所春节、中秋国庆的单项公告已核对，与年度通知一致。
