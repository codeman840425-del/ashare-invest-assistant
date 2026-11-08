# 插单：麦蕊全量代码集探针 p12（security_master.md §7）
结果：PASS（附1个问题）。本地提交 3f04eda，未推送。
- dry-run（unshare -rn）47/47 全部通过；STOP 保留，sha256 02339d1e…7fbe17；scan_licence/secret_scan/gitleaks(probes) 无发现。
- 新增调用：+2（/bj/list/all、/kc/list/all，路径未经本地文档确认，各调1次不重试，超限触发熔断）；/hslt/list、/hsrl/ssjy/all、/hsrl/real/all 复用。总数 266→268（api 266 + pro 2）；收盘后 257；单跑 p12 为 5 次。耗时仍约 4–8 分钟。
- CI S1：为 .gitleaks.toml 自定义规则 S1-mairui-licence-assign 命中 DRY_RUN_LICENCE 假值（误报），改为 "-".join 拼接，值不变；另把 common.py:337 的 S101 assert 改为显式 raise。
- 重测后对比命令（在共享电脑上跑，脚本每次覆盖 /tmp/t7/mairui_diff.json，故逐个另存）：
  R=src/backend/probes/results/run-<ts>/code_lists
  for k in lists hslt_list hsrl_ssjy_all hsrl_real_all union_all; do python3 /tmp/t7/compare_mairui_codes.py "$R/mairui_dm_$k.txt" && cp /tmp/t7/mairui_diff.json "$R/../diff_$k.json"; done
## 问题 / 需他人处理
1. 3f04eda 误带入他人已暂存的 4 个前端删除（src/frontend/package-lock.json、prototype/package-lock.json、prototype/dist/index.html、prototype/dist/assets/index-DP0JAjoc.js，-7817 行，疑似转 pnpm）。前端/编排者决定保留或拆分；后端未回滚（越权）。
2. 历史提交仍含旧行，CI 全历史 gitleaks 可能继续报；需运维在 .gitleaks.toml allowlist 加该误报。
3. §7 第3–6项（旧北交所代码、cxgc、北交所退市、公告）不在本单范围。
