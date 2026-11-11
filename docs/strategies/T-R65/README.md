# T-R65：复测状态输入数据补齐（深市 ST / 沪市 ST / 上市状态 / 终止名单 / runner 接线）

> 依据：T-A154 三条件；任务 T-R65｜2026-11-11 北京时间｜维护：策略研究员
> 分支 `ds/T-R65`（基于 `ds/T-B136@d4405a8`，runner 实现所在分支）；数据本体放 `data/`（gitignored），仓库只入脚本/清单/说明。
> 红线：只读公开源 + 库内已有数据；零麦蕊；不写正式库；产物 sha256 入 manifest。

## 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| ① | 深市 ST 历史（深交所简称变更 → runner 输入） | **完成（本 PR）** |
| ② | 已知子集三件套：沪市 ST（东财逐股倒排）、上市状态历史、沪深终止名单 | 进行中 |
| ③ | runner 接线：三项输入 + coverage 非 null 预检 + 覆盖比例入 summary 首页 | 待做 |

## ① 深市 ST 历史 → runner 输入

**产物**（数据本体在仓库外，按 runner `--st-history` 路径传入）：

| 项 | 值 |
|---|---|
| 数据文件 | `data/retest-inputs/st_history_sz.csv`（gitignored，不入库） |
| CSV sha256 | `869b9542af8571c614da8373fb01fba608a374e344855801c3aae42cda5bb9a1` |
| 生成脚本 | `docs/strategies/T-R65/build_st_history_sz.py` |
| manifest（入库） | `docs/strategies/T-R65/manifests/st_history_sz_manifest.json` |
| 覆盖 | 3,020 只深市 A 股 × 3,553 个区间；372 只有 ST/*ST 段（399 段）；每只从 2022-01-01 连续覆盖到开区间 |
| 来源 | 深交所「上市公司简称变更」xlsx（SSGSGMXX，全历史 1994-01-03 至 2026-11-10；sha256 `9291117a…`） |

**口径（对齐 `data.load_status_history`）**：

- CSV 列 `exchange,symbol,valid_from,valid_to,is_st`；`is_st ∈ {true,false}`；`valid_to` 空 = 开区间。
- 窗口起点之前的状态取「最后一条 ≤ 2022-01-01 的变更」；之后每条变更开新段；无变更记录 → 全程 `false`（简称从未变化）。
- `is_st=true` 仅当简称以 `*ST` / `ST` 开头（NFKC、去空白）；**「退」不计 is_st**（退市整理期由 listing-status 输入处理）。
- **不与 `security_risk_flag_history` 混写**：本产物只来自深交所公开简称变更，独立 sha256 + manifest，不写库。

**复现**：

```bash
uv run --no-project --with openpyxl==3.1.5 python docs/strategies/T-R65/build_st_history_sz.py \
  --xlsx <szse_name_change.xlsx> \
  --hf-manifest data/hf-1min/2022plus/manifest_files.csv \
  --vipdoc-dir <vipdoc/sz/minline> \
  --out-dir data/retest-inputs
```

## ② 已知子集三件套（进行中，待补）

- 沪市 ST：东财逐股礼貌拉取，按「ST 不明股票-日」清单倒排子集（限流纪律照旧）→ `st_history_sh.csv`；与 ① 合并为 runner 的 `st_history.csv`。
- 上市状态历史：库内表（IPO/退市日期等）+ 区间外 unknown 剔除计数（沪深都做）。
- 终止名单：沪深交易所公告页一次做全，人工核对带 URL（177+99 只）。

## ③ runner 接线（待做）

- 接入 `--st-history` / `--listing-history` / `--delisting-list` 三项输入；
- **coverage 三项非 null 预检**（`st_coverage` / `listing_coverage` / `termination_list_sha256` 任一为 null → 拒绝执行，防「输入给了没吃」静默空转）；
- 覆盖比例按交易所按年强制写入 summary 首页。
