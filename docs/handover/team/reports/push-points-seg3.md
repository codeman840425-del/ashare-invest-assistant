# 第三段推送点（2026-11-07 13:55 MDT，架构师）
1. 不会偶发变红的推送点是 076ad51（9ad51b8..076ad51：e6ca937、f6c36ec、f9374be、d2553ec、076ad51），用合并。
2. efb53b8 必须和 aa858a8 同批推。单推 efb53b8 时，冒烟脚本只接受 502，gateway-limits 会偶发变红。但 aa858a8 在 9059bfb（B5）之后，中间还隔着 ef123be、1af8543、20fe5d3 这几个 B 级提交。所以 efb53b8 及以后的提交要等后端修完 B1–B5、f65b3e8 评完，再整段推到 HEAD。
3. 076ad51 之后已评可推的有：efb53b8、a57b2ac、e37f819、3e6cc69、baa4539、ac6c710、1a86cb9、aa858a8。还没评的只有 f65b3e8，正在评。
4. M1（运维，baa4539）：非 local/test 环境下，worker 没设 MASTER_SNAPSHOT_PATH，也没挂快照卷，生产上主数据同步每次都会报错。部署前必须修：设变量、挂专用卷、在 DATA_VOLUMES 里登记，并确认 worker 能访问三所地址。
5. 后端：
   - B1–B5（ruff 和 mypy）还没修；
   - 9059bfb 新增的 app/signals 没有对应 pytest，覆盖率预计不达 90% 门槛，修 B5 时一并补；
   - m：tr12_fin.py 没格式化；交易所同步直接用 urllib 出网，需要对照 plan 的出网约束确认。
6. aa858a8 与 ruling-gateway-502-504 逐条一致，/securities 的 502/504 错误页都带 no-store。冒烟脚本本机跑不了（本机没有 bridge 网络），要等 CI 的 gateway-limits 作业来验证。
7. f65b3e8 已评可推，不需要同批，无 B/M 问题。main 已全部评完；076ad51 之后的提交只等后端修完 B1–B5，就能整段推到 HEAD。
