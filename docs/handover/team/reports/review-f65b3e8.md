# 评审 f65b3e8（CI 网关检查 T-A04 ⑩：666cd6e 评审 m1，和其他指令写在同一行的 proxy_pass 也要识别）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；本机 Shell，在临时克隆 /tmp/rv4 里跑，只读，没有推送，没动 dockerd，也没动容器。
- 改动：新增 directive_re(name)。指令既可以在行首，也可以跟在 `;`、`{`、`}` 后面；参数可以换行。proxy_pass 和 proxy_connect_timeout 都改用它。
- 666cd6e 的 m1 关闭：原来 `location / { proxy_pass <url> }` 这种写法会漏检。
- 不会误判：x_proxy_pass、$proxy_pass 这类名字不匹配；读配置时先跑 strip_comments（check_gateway_limits.py:72、82），注释里的指令不计入。
- 新增用例覆盖：同一行写多条指令、一行里有多个 proxy_pass、参数换行、server 级 connect_timeout 写在同一行、location 级把超时放宽到 30s 被拒。
- 实测：test_gateway_limits 130 通过；check_gateway_limits 对当前 nginx.conf 报 0 个问题，这次收紧没有把现有配置判成违规。
- 只改 scripts/ci，不影响运行时，也不需要同批推送。
- B/M：无。
