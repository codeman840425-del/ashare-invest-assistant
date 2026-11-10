# T-T82 复测执行单（T-B136 交付后执行；预案预热，本单不跑复测）

- 北京时间 2026-11-11 起；分支 `ds/T-T82`，基线 `origin/main=465e020`；worktree `.worktrees/ds-T-T82`。
- 角色：测试。本单只写执行预案，不动业务代码、不下载数据本体、不跑复测、零麦蕊。
- 输入：issue #3 正文与评论（Grok 编排者 2026-11-10 两条数据指令）、`data/data-kit/README.md`（§1 HF/§2 tdx/§3 vipdoc/§4 通过判据）、`ds/T-T81=41c58e4` 的 `tests/backend/retest/test_splice_validation.py`（24 用例：15 常绿 + 9 pending）、`docs/strategies/T-R58/retest_plan.md`（6814edc 版，T-A148d 复审通过后为准）。
- 数据区现状（2026-11-11 实测）：`data/hf-1min/raw` 15.1 GB / 6599 文件**仍在下载中**（目标 43 GB / 5801+viewer 文件）；`data/tdx-pack/` 已解压 hsjday+gbbq，`T-B136-tdx-manifest.json` 哈希与工具包对照一致（hsjday b6c2a504…，gbbq c1cbc818…，索引覆盖至 2026-11-10）；`2022plus` 未生成；`D:\西部证券\vipdoc` 可访问。

## 一、数据准备验收（README §4 四条，逐条定点命令与判据）

| # | 验收 | 定点命令 | 通过判据 | 失败分级 |
|---|------|----------|----------|----------|
| D1 | HF 原始快照 SHA | `python -c`（README §1 内置校验脚本，raw 目录 + `raw_expected_sha256.txt`） | `ok=5801 mismatch=0 missing=0`，exit 0 | **阻断**：任一 mismatch/missing 不得转换、不得开跑；重下对应文件后重验 |
| D2 | 转换产物 manifest | `python scripts\convert.py --raw … --out data\hf-1min\2022plus --start 2022-01-01 --drop-dates 2026-08-07 --workers 8 --revision ba589a11534825044fe5a6b84838f50ba8d8d188` 后对照工具包 `manifest.json`/`manifest_files.csv` | 控制台 `files=5714 errors=0`；`source_repo/revision/parameters.start/parameters.drop_dates/source_files=5795/files=5714/stocks_by_exchange(SH2383,深3004,北327)/delisted=180/empty=81/failed=0/total_rows=1391541837/first_ts=2022-01-04T09:31+08/last_ts=2026-08-06T15:00+08` 全对；csv 5714 行。不比对 raw/out/generated_at 路径字段 | **阻断**：行数/股票数不符=转换失败；sha/bytes 因 pyarrow 版本不一致但行数、交易日数、起止时间一致→抽 3 只内容核对后放行（记录 pyarrow 版本）；北交所 327 只可不计入（复测不用） |
| D3 | tdx 日线+权息 | 对照 `data/tdx-pack/T-B136-tdx-manifest.json`（hsjday 12242 文件、gbbq 26 文件）；哈希与 README §2 参考值比 | hsjday.zip/gbbq.zip sha256 = b6c2a504…/c1cbc818…；官网已更新致哈希不同时，以「能覆盖到 2026-11-10」为准并记档新哈希 | **记录级**（官网更新属预期）；覆盖区间不足 2026-11-10 才升级为**阻断** |
| D4 | vipdoc 只读 | 只读枚举 `D:\西部证券\vipdoc` 沪深 lc1/lc5 | 沪 2321+2321、深 2908+2908，合计 10458 文件；原文件 mtime 未变 | **阻断**：数量缺口>1% 报后端/编排者裁定；绝不写该目录 |

- D1–D4 全过后才允许正式开跑（issue #3 评论口径）。判据与 issue #3 Grok 评论 6777783330 逐字对齐，冲突时以 issue 为准并报编排者。

## 二、T-T81 pending 9 条接线（后端 `SpliceChecker` 落地后）

- 接线方式（照 T-T81 docstring）：占位 `SpliceChecker` → `from app.retest.splice import SpliceChecker`（模块名以后端落地为准），**断言本体不改**；接线后 24 collected / 0 error、15+9 全 passed。
- 接线复测命令：`python -m pytest tests/backend/retest/test_splice_validation.py -q --tb=short -p no:cacheprovider`（在 T-B136 分支或合并后基线）。
- 通过判据：§2.7 第 1/4/5/6/7/8 条断言全绿——北交所=0 与 920 前缀不进池、不可配对股计数不 fail、抽査股不进复测区、重叠一致 ≥98% 仅限抽查股、双包原始+gbbq 自算、`check4` 任一失败即停且带代码清单、失败语义落 `summary.json` 的 `splice` 节点。
- 分级：接线后任何断言红 = **阻断**（后端返修，不记「业务已通过」）；skip 未消除 = 后端模块未落地，如实报阻塞。

## 三、复测执行监控点（开跑后逐项核对，照 issue #3 验收节）

| # | 检查 | 判据 | 分级 |
|---|------|------|------|
| R1 | 前视检查用例 | 全部 passed | **阻断** |
| R2 | R 组随机对照 | 均值 ≈ −往返成本且显著为负、n 与 A* 逐腿 1:1；≈0 或 >0 按研究员 T-R59 框架=实现问题红旗 | **阻断** |
| R3 | 34 组参数齐 | trials.csv/legs.csv/summary.json 产出、可复现（固定种子、revision+manifest sha 入 summary） | 缺件=**阻断**；数值判读归研究员 T-R59 框架，测试只验产出与可复现 |
| R4 | 环境纪律 | 零麦蕊调用（MAIRUI_MODE=replay 台账零新增）、不写正式库、结果只落 `reports/T-B136.md` 及附件、不对外发信号 | 违例=**立即停止**并报编排者 |
| R5 | 门禁 | gitleaks、secret_scan、mypy、alembic 单 head、checker 两种模式（前端不涉及）全绿 | **阻断** |

## 四、测试侧执行边界

- 定点跑上述 D/R 各条，不跑全量 pytest/coverage；本地数据只读，`D:\西部证券\vipdoc` 与 `data/` 下载目录绝不写入。
- 不读密钥、`.env`、`.credentials.yaml`、bot secrets；不打印行情明细到报告。
- 正式复测由后端 T-B136 主跑；测试只做 D1–D4 门禁复验 + R1–R5 独立核验 + T-T81 接线复测，结论进 `docs/handover/team/reports/T-T82.md` 并更新 progress-board 对应小节。

## 五、状态

- 预案已落盘（本文件）；等后端 T-B136 交付令即按此执行。
- DeepSeek：未用，预案编写无需外发。
- 申请新任务：无（等 T-B136 交付令）。
