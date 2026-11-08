# T-O28 用户机 nginx 500 只读采证（运维，2026-11-07 21:31 MST）
机器 cf606eaa；用户机 HEAD d313d64；全程只读，没重启或修改任何东西。命令都走原生审批，没有被拒绝或超时。
现象：8080/ 和 8080/login 返回 500（170B）；/health/live 返回 200。
nginx 错误日志（docker logs 2>&1，在 bash 里取，原样摘录，不含秘密）：
  [error] rewrite or internal redirection cycle while internally redirecting to "/index.html", request: "GET / HTTP/1.1"（/login 相同）
容器内 /var/log/nginx/error.log 是指向 /dev/stderr 的软链，access.log 指向 /dev/stdout；没读 FIFO。
镜像：容器和 aia-frontend:aia-local 是同一个镜像 sha256:d3f6f4c02d02…ee28，构建时间 04:01Z（MST 21:01），容器创建于 04:12Z。
挂载：只有两个只读 bind：deploy/nginx/nginx.conf→/etc/nginx/nginx.conf，deploy/nginx/limits.dev.conf→/etc/nginx/aia-limits.conf。
静态文件：/usr/share/nginx/html 共 3.3M，root 属主，755/644；index.html 存在（1001B）；assets/ 存在，文件齐全。
nginx -T：语法 OK。配置只有 try_files：/assets/ 是 `$uri =404`，/ 是 `$uri /index.html`。整份 nginx -T 里没有任何 root 指令；仓库的 nginx.conf 只 include 了 mime.types 和 aia-limits.conf，不 include conf.d。
上游：容器内 getent api 解析到 <host>；wget api:8000/api/v1/health/live 返回 {"status":"ok"}。
结论（有证据，属于 deploy 配置，不是业务代码）：
- 挂载进去的 nginx.conf 替换了镜像自带的 default.conf，又没写 root，所以用编译期默认的 <prefix>/html（官方镜像是 /etc/nginx/html），而不是 /usr/share/nginx/html。
- 结果是 /index.html 找不到，try_files 回退形成循环，返回 500。
- 未实测部分：最后一条确认 prefix 和 /etc/nginx/html 是否存在的只读命令执行失败（exit 1，没有输出），我没重试。推断依据是“没有 root 指令”和“循环日志”这两条证据。
建议交 cloud：在 nginx.conf 的 server 级加 `root /usr/share/nginx/html;`（让 CI 的 check_frontend_deploy/网关 smoke 覆盖这一点）。之后由我机械集成，并在用户机只做 nginx 重建或重启加 HTTP 自检。
基线包：artifacts/T-O28-baseline.tar.gz，69 个文件，来自 d313d64。
DeepSeek：用于通用采证报告框架（产出目录 reports/deepseek/T-O28/），没发送实际日志，结论由我自己复核。
