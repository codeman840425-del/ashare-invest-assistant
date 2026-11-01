"""每用户数据证书（契约 v0.2.6，plan §2.1B，T-A07 / T-B45）。

- :mod:`.hpke`：RFC 9180 Base 模式单次加密
  （DHKEM(X25519, HKDF-SHA256) + HKDF-SHA256 + AES-256-GCM）。
- :mod:`.keys`：封装公钥/私钥文件的解析（api 只有公钥；私钥只给 ingest）。
- :mod:`.seal`：证书封装/解封、AAD、去重 HMAC。
- :mod:`.service`：api 侧的数据库与 Redis 操作（状态视图、事件、验证意图）。

证书明文只在请求处理的内存中短暂存在：不写日志、不回显、不入库（库里只有密文与 HMAC）。
"""
