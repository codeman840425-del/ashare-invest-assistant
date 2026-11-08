# review-8e8525e（T-B63，B1–B5 收口）  结论：代码可推；后端 CI 仍红（非本提交引入）
- B1/B2 ruff check 0、mypy --strict 0（HEAD cc5ea15，115 文件）。
- B3 reconcile.py:104 是变量遮蔽改名（key/old→diff_key/open_row，name→source_name），真修，不是 ignore；原运行行为本就正确。
- B4 test_tb63_signals.py 放在 selfchecks/，CI 不收集；覆盖退市（delisted/delist_date/退市整理期只挡买入/加仓），**没有停牌守卫**："suspended" 按设计抛 ValueError，停牌规则是 T-B60 验收③，尚未实现 → M（后端补实现，测试员补用例）。
- 覆盖率（main + test/T-T01）：signals 100%（41/41，但依赖本机他人的 tb58-isolated-pg3 容器，CI 上不成立）、domain 65.7%、importing 71.6%，总 74.82%（<80）→ B（后端补测试）。
- CI 模拟 076ad51..HEAD：只有 main 时 tests/ 只剩 d5dd1f8 的最小集，总覆盖 0% → pytest 和 check_coverage 都红；合入 7f94033 后 1 failed / 3 errors / 总覆盖 74.82%。
- failed：test_backend_business_files_equal_plan_6_1，config/share_class_list.yaml（20fe5d3）未登记到 plan §6.1 → M（架构师补 plan §6.1）。
- 区间内未评审的代码提交：仅 8e8525e，本次已评。secret_scan range 076ad51..c30ac58：181 个文件版本，0 block。
- 同批：ef123be、1af8543、20fe5d3、9059bfb 必须和 8e8525e 一起推（lint 修复）。
