# push-seg3 结果（2026-11-07 14:01 MST）
- origin/main = bd28652c06f4ba0ca67778d6a937c5a8864d55ca（父 1c8d2fd + 076ad51，6 个提交，止于 076ad51）
- secret-scan 42413355137：success — <url>
- ci 42413355113：failure — <url>
  - backend：241 个测试通过；总覆盖率 0%（0/8425），app/importing 0%，低于门槛
    - 原因（T-O16 已确认）：只跑了不调用 app 的夹具测试
  - gateway-limits：上游删除后返回 504（应为 502）；efb53b8 + aa858a8 在后续批次
- 未重跑，未改代码，未再推送
