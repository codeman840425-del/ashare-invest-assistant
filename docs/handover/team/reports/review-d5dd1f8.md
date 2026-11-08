# 评审 d5dd1f8（T-T26，测试）——通过，0 B / 0 M
- 范围：12 个文件，全部在 tests/ 下（conftest、pytest.ini、unit/*、fixtures/fmt_a/*）。
- 在临时检出里实测：
  - pytest tests/backend/unit：241 个通过；
  - check_fixtures.py：0 个失败，含 SYNTHETIC 标记、generate.py 能逐字节复现、契约 §4.1 的 46 个码全部覆盖；
  - secret_scan range 61b0edf..d5dd1f8：阻断 0，警告 0。
- 能修好 CI 里 backend（找不到测试）、fixtures、secret-scan 三处失败。gateway-limits 要等 T-O14。
- 合并检查：与当前 main HEAD 没有冲突；与 test/T-T01 5c0fec5 在 tests/backend/unit/test_expected_json.py 有 add/add 冲突。
- 推送顺序：
  1. 把 d5dd1f8 快进推到 origin/main（父提交是 61b0edf）；
  2. 本地 main 合入或变基到 d5dd1f8；
  3. 测试把 test/T-T01 变基到 d5dd1f8，解决上述冲突后再提交评审。
- 注：本机 /tmp/gitleaks-bin 已不在，这次改用仓库自带的 secret_scan.py 扫描。
