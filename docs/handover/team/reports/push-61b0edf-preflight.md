# push-61b0edf 推送前只读核验（未推送）
- 仓库：/workspace/ashare-invest-assistant（当前分支 main，HEAD f65b3e8，未改动）
- 目标 61b0edf0262222a8349ef4631425366e70f4fdb8；基点 0cb78ad511497bd493082d63910a81c83b0c5a86
- origin/main（本地与 ls-remote 一致）= 0cb78ad511497bd493082d63910a81c83b0c5a86
- 0cb78ad 是 61b0edf 祖先：是（可快进）；范围提交数 85，merge 0；61b0edf 在本地 main 内
- 3e5e288 不在范围内（不是 61b0edf 祖先），2954b6c 也不在目标内；目标树 .gitleaksignore 仅 3 条 ccf7cba 旧条目
## 扫描（gitleaks 8.30.1 /workspace/.ops-tools，配置取自目标树 61b0edf，--ignore-gitleaks-allow，--redact）
- gitleaks 范围 + 目标树 ignore：0
- gitleaks 范围 + 不用任何 ignore：0（零命中不依赖忽略）
- secret_scan.sh range：635 个文件版本，阻断 0，警告 0
- check_real_secrets.sh range（真实值比对，不打印）：FOUND 0
- 原始日志：/workspace/team/reports/.preflight-61b0edf/（700/600）
## 结论：无阻塞，可按 `git push origin 61b0edf:refs/heads/main` 快进推送（待主代理决定）
