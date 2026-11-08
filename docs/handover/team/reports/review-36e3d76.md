# T-B61｜36e3d76 评审
结论：本提交 B=0、M=0；单项修复通过，可随修复后的 T-B61 推送，不构成整段可推批准。
范围：仅 master/vendor.py 的 deadline_for 分支与 selfchecks/tb61.py 新增三组断言 diff。
修复：manual 严格寻找下一个既有工作日傍晚/次日补拉槽，周五晚→周六早，周六早后→周一晚，周一早前→周一晚。
相关 pytest：新增独立无外呼用例复核三组及恰好18:00边界，4/4 PASS；同轮规范化/意图/扫描共12 PASS。
ruff：受影响文件 PASS；mypy：master/vendor 在8模块检查中 PASS。
覆盖率：master/vendor 整文件28%（本轮只跑定点单测），不是整模块90%达标；JSON见 rv7-vendor-coverage.json。
七点核对：仅改变验收⑥的 manual deadline；①–⑤、⑦不受本 diff 影响，继承 b4539c2 未验收部分及 M1/M2。
原 selfchecks 未执行：硬编码他人库/Redis 且 flushdb，违反本轮隔离约束；不以其既有111项报告代替本轮实测。
推送：不推送；整体仍待 b4539c2 M1/M2 与七点隔离集成/权限/覆盖率补验，不得宣称 T-B61 全通过。
