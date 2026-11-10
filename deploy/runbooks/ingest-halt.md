# ingest 停机标志（T-O66b）

## 路径（与 compose / 镜像约定一致；后端按此改常量）

| 用途 | 最终路径 | 载体 |
|------|----------|------|
| 状态根（ingest 独占） | `/run/aia/state/` | 具名卷 `<前缀>_ingest_state`，属主 10001、700 |
| 停机标志目录 | `/run/aia/state/halt/` | 同上（例：`…/halt/mairui-daily.HALTED`） |
| 授权收据目录 | `/run/aia/receipts/` | 具名卷 `<前缀>_aia_receipts`，root 属主；ingest/worker **:ro** |
| 解密临时文件 | `/run/aia/tmp/` | ingest **独占 tmpfs**（mode=0700,uid=10001,noexec,nosuid） |

装入收据的步骤见 `receipts.md`。**只删收据文件不能恢复出口**（权威来源是数据库 `upstream_halted` / 停机标志，解除须用户本人确认，见下文）。

旧路径对照（后端待改）：`/run/aia/mairui-daily.HALTED` → `/run/aia/state/halt/mairui-daily.HALTED`；`/run/aia/mairui-daily.tmp` → `/run/aia/tmp/mairui-daily.tmp`；`/run/aia/authorizations/mairui-daily.json` → `/run/aia/receipts/mairui-daily.json`。

## 换机 / 重建语义

- **权威来源是数据库**（如事件行上的 `upstream_halted` / `ops.data_licence_events` 中 ingest 写入的限流暂停）。卷里的停机标志只是本机缓存。
- 文件丢了（新卷、换机、误删）也照样停；不要靠「文件不在了」来判断可以恢复外呼。

## 解除停机标志（必须由用户本人确认）

1. 先确认数据库侧限流/暂停条件已消除或用户明确要求恢复（人工核对，不自动）。
2. **解除必须由用户本人确认**后，再删本机标志文件，例如：
   ```bash
   deploy/scripts/compose.sh exec -u 0 ingest rm -f /run/aia/state/halt/mairui-daily.HALTED
   ```
   （路径以实际文件名为准；不要在未获用户确认时删除。）
3. 不要手工清理 `ops.data_licence_events`（见 `database.md` §6.1）。
4. 旧部署若仍有 `<前缀>_aia_run` 卷：T-O66b 已不再挂载；确认无需要后可人工删除该卷，不自动迁移内容。
