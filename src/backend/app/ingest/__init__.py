"""行情采集服务 ``ingest`` 的纯逻辑模块（plan §2.1A / §2.1B，T-A07，T-B04a-x）。

这里只有**不联网、不读数据库、不读 Redis**的纯函数与类，便于回放测试：

- :mod:`.upstream`：把麦蕊响应（HTTP 状态 + 响应体）归类为调度信号；
- :mod:`.bucket`：每证书令牌桶与北京时间日计数；
- :mod:`.state`：按证书的状态机（invalid / quota / ip_limited / 退避 / 熔断 / 到期 / 管理员暂停）；
- :mod:`.scheduler`：每证书 P0/P1/P2 队列 + 证书间 DRR + 全局/每证书并发；
- :mod:`.vault`：HPKE 解封（只在 ingest 进程）与证书明文脱敏；
- :mod:`.intents`：``ingest:requests`` 意图解析（``verify_licence``）与 ``data_sharing`` 取数归属；
- :mod:`.expiry`：到期提醒（30/7/1 天）。

真正的外呼循环、Redis 单活锁与 DB 写回由后续任务接线；本包不引用任何 HTTP 客户端。
"""
