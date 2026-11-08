# 评审 2f24538

- 评审人：架构师；日期：2026-11-01（America/Denver）
- **说明**：任务把 2f24538 列为“T-O12 主密钥备份脚本”。该提交**已找到**（`git cat-file -t` = commit，在 main 上、未推送），但它**与 T-O12 无关**——是用户给错了 hash。T-O12 的实现只有 b195ca6（见 review-b195ca6.md）。
- 实际内容：`fix(deploy): nginx 414/请求头过大返回 JSON 信封 + X-Request-Id（与 413 一致），CI 规则 10`。T-O11.md §5 / §8 把它列为“待复审”，这里顺带做简短评审。
- 方法：干净导出到 /tmp/rv/2f24538；`check_gateway_limits.py` rc=0；`test_gateway_limits.py` 54 passed；运维在 aia-t01 的实测见 T-O11.md §5（20000 字符 URI → 414 JSON；9000 字节 Cookie → 400 JSON；413、meta、401 不变）。

## 结论：**可以推送**（无 B / M）

## 核对
- `deploy/nginx/nginx.conf:62` server 级显式 `large_client_header_buffers 4 8k`（= nginx 默认值），信封 `max_bytes=8192` 与之一致，CI 规则 10 检查两者一致、limits*.conf 不得再写。✅
- `nginx.conf:171` 414 用 internal URI location（不是命名 location，避免读请求行阶段 “empty URI in redirect to named location” → 500），带 `X-Request-Id`、`Cache-Control: no-store`。✅ 外部直接访问 `/__aia_errors/414` 因 `internal` 得 404。✅
- `nginx.conf:183` 494 → `=400` 命名 location，JSON 信封。✅
- 414 `URI_TOO_LONG` 已由 docs 4b40e5c 登记契约 §4 / #34，前端 d9c045f 同步。✅

## 问题
- **m1** `deploy/nginx/nginx.conf:183-189`：`REQUEST_HEADER_TOO_LARGE`（400）至今**未登记契约** §4 / `/meta/enums.error_codes`（契约里只有 `URI_TOO_LONG`）。契约 §1.3 要求错误码都在表内。修复（架构师）：下次契约修订时在 §4 登记 `400 REQUEST_HEADER_TOO_LARGE`（网关级，`details.max_bytes`，判定顺序排在 414 之后、413 之前），后端 OpenAPI 与前端 ERROR_CODES 同步；登记前前端按通用错误显示 `message`，不阻塞。本次按任务只改 plan，不动契约。
- **n1** `scripts/ci/check_gateway_limits.py:293-294` 的正则要求指令独占一行开头；同行多指令写法（`server { large_client_header_buffers …; }`）不会被识别。与 666cd6e 的 proxy_pass 正则同一类问题，一并按 review-666cd6e m1 处理。

---
裁定登记：docs/plan.md 本地提交 1294476（未推送）——A 网关 `proxy_connect_timeout 3s`（运维）；B 主密钥多版本为上线门槛，新增后端任务 **T-B57**，重加密 CLI / 轮换流程放 V2（运维在 T-O12 之后跟进），契约不变；§9 问题 95（默认执行，用户可改，上线推迟一个后端任务的工作量）。
