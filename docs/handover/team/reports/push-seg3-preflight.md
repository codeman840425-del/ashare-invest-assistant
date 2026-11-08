# push-seg3 推送前核验（未推送任何 ref）
- origin/main（ls-remote）= 1c8d2fd94c4bc3eca92038927163b3dc11193f93
- 待推 bd28652c06f4ba0ca67778d6a937c5a8864d55ca：在 1c8d2fd 上 merge --no-edit 076ad51e798b737e4ddce2899ae7f7ace33f078b，无冲突
  - worktree /workspace/wt-ops-seg1，分支 ops/seg1-merge；父 = 1c8d2fd + 076ad51，可从远端快进
- 范围 1c8d2fd..bd28652：6 个提交 = e6ca937、f6c36ec、f9374be、d2553ec、076ad51 + 1 个 merge，没有其他提交
- 排除证明（祖先检查）：efb53b8、aa858a8、a57b2ac、e37f819、3e6cc69、baa4539、ac6c710、1a86cb9、f65b3e8、ef123be、1af8543、20fe5d3、9059bfb、7c0548a、8cfa952 都不在范围内
- gitleaks 隔离扫描（源目录指向 .git，配置用目标自身的，ignore 6 条，配置与 1c8d2fd 相同）：5 个提交，不用 ignore 0，用 ignore 0
- secret_scan range：40 个文件版本，阻断 0；check_real_secrets：FOUND 0
- 结论：0 命中，可快进推送：git push origin bd28652c06f4ba0ca67778d6a937c5a8864d55ca:refs/heads/main
- 日志：reports/.preflight-seg3/（700/600）
