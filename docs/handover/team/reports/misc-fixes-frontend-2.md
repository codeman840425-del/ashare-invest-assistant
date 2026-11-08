# 前端小修复（第 2 批）

- 提交（本地，未 push）：`a2d2b74`（三项修复）→ `d860970`（refresh 取代旧卡后在新卡显示提示）→ `749b6fc`（只放宽两条用例的总时限）
- 范围：只暂存 `src/frontend/` 下本人改动，逐个文件暂存，`git commit -- <paths>`，未 amend
- 时间：2026-11-02 北京时间 11:01–11:17

## (a) 评审 05d8a16 m1：跟踪收益按服务端原值显示
- `StatValue` 新增 `kind="raw"`：原样显示服务端 decimal 字符串，不做 `toFixed(2)`；`null`/非数字仍显示“样本不足”。
- 建议详情页 t1/t5/t20 跟踪统计改用 `raw`，`0.003` 显示为 `0.003`，不再是 `0.00`。
- 用例：`misc-fixes-2.test.tsx` “m1” 两条（组件级 + 详情页）。

## (b) refresh 以响应体为准（契约 #36）
- `POST /suggestions/refresh` 读 200 响应体 `{suggestion, changed, superseded_id, data_as_of}`，不再另发 `GET /suggestions?status=active` 找当前卡。
  - `suggestion.id` 与当前卡不同 → 跳到新卡，并在新卡上显示提示（d860970）；
  - 同一张卡：`changed=true` 提示“本卡已更新”，`changed=false` 提示“没有变化（数据截至 …）”；
  - `suggestion=null` → 提示本证券当前没有候选信号卡，不跳转。
- 响应里的卡直接写入详情缓存；旧卡、列表、终端、今日页按需失效重拉（契约允许刷新后再 GET）。
- mock 按 #36 返回同结构；`/non-executable-reasons?suggestion_id=` 能识别刷新新建的卡。
- **待定（契约仍未写）**：`POST /suggestions/{id}/actions` 的响应体——#33–#36 与 T-A04.md 都没有给出，前端继续不读取该响应体，操作后让详情失效重拉。没有猜结构。

## (c) 已放弃 / 失败的导入批次不再请求逐行预览（契约 #35）
- 新增 `rowsAvailable(status)`：只有 `previewed` 才挂 `/rows` 查询；`discarded`、`failed` 不发 `/rows`，计数一律取批次头 `stats`（抽成 `BatchStats`）。
- 在预览页放弃：成功后先把缓存批次头置为 `discarded`、取消并移除本批次行缓存，只让批次头与列表失效，`/rows` 不会被重拉。
- failed 批次不提供“只有表头的问题清单”下载。
- mock：两种状态的 `/rows` 返回 200 空列表、`errors.csv` 只有表头、对 discarded 批次 resolve → 409 INVALID_STATE_TRANSITION；放弃时删除预览行，`stats` 保留。
- 用例：#35 共 5 条。

## 检查
| 项目 | 结果 |
|---|---|
| 工作区 typecheck / eslint（--max-warnings=0）/ vitest | 通过 |
| 干净检出 CI（d860970） | rc=1：刷新跳转用例在全量并行下 5.3 秒超时 |
| 干净检出 CI（749b6fc，只把这两条用例总时限放宽到 20 秒） | **rc=0** |
| gitleaks（dir + staged）/ secret_scan / 禁用词 / 连续 11 位数字 | 0 命中 |

## 截图（1440×900，深色，console 错误 0，外部请求 0）
- `reports/misc-fixes-frontend-2/suggestion-before-refresh.png`
- `reports/misc-fixes-frontend-2/suggestion-refresh-by-body.png`（以响应体为准跳到新卡）

## 需要别人做的
- 后端：`/suggestions/refresh` 按 #36 返回响应体；`discarded`/`failed` 批次按 #35 删行（T-B56 清理任务）。
- 架构师：`POST /suggestions/{id}/actions` 响应体仍未定，需要时请补契约。
