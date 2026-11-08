# T-O32 已验收提交盘点与试合（运维，2026-11-08 17:05 北京时间）：只是试合，没动库、服务或共享 main
做法：从各任务报告里抽出精确 hash，逐个核对是不是 96a4b683a658bfecb2d2446f2b71120832e5c872 的祖先。
已在 96a4b68 里：
- 后端：P2N-02 273be2d；P2N-03 2f516b5、825b682；P2N-04 b171567；P2N-07 16f2a1a、9dd6047；T-B89 750e2ed；T-B90 0e32585。
- 前端：05a e25894b；05c a94e234、d215296；05d d98ebec；05e 148fc8e；05f a36eb1e；05g c6d4ffa。05b 没有 .md 报告，只有 P2N-05b/ 目录，没核到 hash，待核实。
- 研究员 6fb2f46；架构师裁定：T-A20 到 T-A31b（1f8e455、T-A21 各 hash、264f570、8ab27c2、6df3148、7f5b061、943ae52、96a4b68）；T-A23 的 4f3ce14、e31ed6c。
不在 96a4b68 里：
- test/T-T01 d0a6644（T-T22，编排者已确认纳入）。比 main 多 39 个提交，包括 3b2c8ec，全部只改 tests/（98 个文件）。
- ops/T-O31 f0785823c8ba4bbd7102fa9b35cd21ed02b69e96（运维：T-O29 → merge T-A30 → T-O30 → T-O31 → 缓存修复）。
- fb6f971（T-A32 评审，有条件通过），已经在共享 main 9b5ab11 里，但它依赖 6d096cd（P2N-R08 golden oracle）。还有 9b5ab11（P2N-05h）。这三个都不在我的验收清单里，没合，待编排者确认。
- 44cf748、caa1f09 是 rebase 前的旧提交，只在 backup 分支，已被取代，不是候选。
试合：worktree /workspace/wt-ops-T-O32，分支 ops/T-O32-trial，基线 96a4b68。顺序：
1. merge --no-ff d0a6644 → 9cd2672437ebbb6450b7424adf9b8d0b828a4fbe，无冲突；
2. merge --no-ff f078582 → 03df03be873373511eebbd749db7085c8768d163（父提交 9cd2672 和 f078582），无冲突。
- 原提交都保留，没有 rebase 或 reset。相对 96a4b68，tests/ 以外只多了 7 个 deploy/CI 文件。
扫描：secret_scan range 96a4b68..HEAD（673 个文件版本）阻断 0；gitleaks range 退出码 0。
没跑测试，没建库，没启动服务，没 push。
待核实：
1. 05b 的 hash；
2. 6d096cd、fb6f971、9b5ab11 要不要纳入；
3. 收口基线用 03df03b，还是在纳入第 2 项之后重新试合。
DeepSeek：未用，原因：只做机械盘点和试合。
