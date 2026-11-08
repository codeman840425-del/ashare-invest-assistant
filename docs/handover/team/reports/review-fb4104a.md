# 评审 fb4104a（T-B49c：当日收盘新鲜度、0017 降级预检、鉴权/CSRF 先于 JSON 400）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- latest_close_at 按 trading_calendar 取值，没有日历时按工作日回退；15:00 之前取前一交易日。price_at 也统一为北京时间 15:00，比较口径一致。
- 0017 降级时，若存在 purpose='horizon' 的行就报 RuntimeError，不删数据。
- body_order 只处理 json_invalid：先跑 current_auth/current_admin，依赖被覆盖时跳过。
- 实测：tb49c 26/0 通过；全量 pytest 0 失败，其中 CSRF 双提交、畸形体判定顺序的用例都通过。
- 注：契约 §9-1209 要求外站 Origin 的 login 返回 403。本提交还没有 Origin 校验，由第二段的 3820276 实现，不在本提交范围内。
- B/M：无。
