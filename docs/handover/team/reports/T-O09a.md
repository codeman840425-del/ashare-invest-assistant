# T-O09a 报告（运维）

更新时间：2026-11-02 06:59 (Asia/Shanghai)

## 结果
- 提交 713a276（T-O09a）已快进推送：
  - 收窄 .gitignore 的证书规则；
  - 新增 `scripts/ci/check_ignored_sources.py`：源码 import 指向被 .gitignore 忽略的文件时报错，带正反自测 `test_ignored_sources.py`；
  - CI 新增 ignored-sources job，用的是干净检出；
  - 新增 `scripts/ci/clean_check.sh`：在临时 clone 里检出提交，跑和 CI 一样的步骤，不碰工作树。
  - 没有改 src/、tests/、docs/。
- `git ls-files -oi --exclude-standard`：只有缓存、备份和 .env 这类本来就该忽略的文件，没有源码。
- 713a276 的 CI run 41357742954 结论是 failure，各 job 情况如下：
  - 成功：ignored-sources、secret-boundary、gateway-limits、migrations、image、licenses、pip-audit。
  - 失败的 4 个都不是 T-O09a 引入的。干净检出把工作树掩盖的问题暴露出来了，这正是 T-O09a 要达到的效果：
    1. contract：check_contract 期望 23，契约是 22。已由 T-O10 的 ec6c58d 改为 22；0cb78ad 上静态步骤已通过。
    2. frontend：`./licence` 只在工作树里，没有提交。已由 527b65e 修复；0cb78ad 上 frontend 已经是 success。
    3. backend：仓库里没有后端测试目录（src/backend/tests、tests/backend、tests/replay），需要测试合入 T-T01。
    4. fixtures：fmt_a 缺 fake_identifiers 和 expected.json，§4.1 有 46 个码没有夹具覆盖，属于测试的 T-T09 和 3.5A-2。
- 后续在 T-O10 里让 clean_check 跟 CI 同步（0cb78ad）：gateway-limits 加了 nginx 冒烟，migrations 加了分库角色两次应用和验收。

## 提交 hash
713a27660b1c090027f3320aa91c698d05b823fc；同步改动在 0cb78ad511497bd493082d63910a81c83b0c5a86。

## 远端 main hash
0cb78ad511497bd493082d63910a81c83b0c5a86（T-O10 推送后）

## 遗留问题
1. backend 和 fixtures 两个 job 会一直红，直到测试补上 T-T01 测试骨架和 T-T09 夹具。
2. CI 还没全绿，原因见 T-O10 报告的遗留问题。
