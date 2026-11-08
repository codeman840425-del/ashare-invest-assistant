# push-points-seg4（076ad51..HEAD，合并推送，不变基）
## 本次推送：origin/main d5dd1f8 → c548924（停在 b4539c2 之前）
1. 先把 3e6cc69、f65b3e8 及之前已评审的部分推到 c30ac58（含合并提交 28b0cf8）。
2. 然后推 cc5ea15 → c548924（docs，T-A10）。
## 同批要求
- efb53b8 与 aa858a8 同批；20fe5d3 与 7c0548a 同批。
- ef123be、1af8543、20fe5d3、9059bfb 与 8e8525e 同批（lint 修复）。
- 建议 test/T-T01（7f94033 及之前）与 main 同一窗口合并，否则 main 上测试只剩最小集。
## 被挡住的提交（链序：c548924 → b4539c2 → 36e3d76 → 1492c80 → c104c05 → 775ba24）
- b4539c2、36e3d76：等 T-B61b → 后端。
- 1492c80（docs）：被链序挡住。要本次带上只能 cherry-pick 到 c548924 之上，需协调方批准，否则等下一批。
- c104c05：评审已过（m 级），被链序挡住 → 运维随下一批推，或与 1492c80 一起 cherry-pick。
- 775ba24（T-B66，测试）：未评审，挡住。
## 推送后预计的 CI
- 前端、ops、secret_scan、scripts/ci：绿。
- backend lint、typecheck：绿。
- backend pytest 和 coverage：红。只有 main 时覆盖率 0%；合入 T-T01 后为 74.82%，domain 65.7%，importing 71.6%。
## 谁来修
- 覆盖率（domain/importing ≥90，总 ≥80）、停牌守卫：后端。
- T-T28 不可移植（git show、/tmp 证据、固定容器）：测试员。
- plan §6.1 登记 share_class_list：架构师。
- c30ac58 M1 序列 USAGE：运维（后端先确认 schema）。cc5ea15 M1 交易所连通性：运维。
## 架构师补充（14:20 MDT）
- c548924 之后又多了 f7e50e8（T-R14 裁定）、1842522（§6.1 裁定）、53fbc91（T-F20，未评）。这几个和 1492c80 一样，都排在 b4539c2 之后，等下一批一起推，不 cherry-pick。
- 1842522：share_class_list.yaml 属于参考数据，不进 BUSINESS_FILES，后端另设 REFERENCE_FILES。由后端改，不改测试；改完 test_backend_business_files_equal_plan_6_1 就会转绿。
- 下一批待评：775ba24（T-B66）、53fbc91（T-F20）、7bd93e6（T-T27），以及 T-B61b。
