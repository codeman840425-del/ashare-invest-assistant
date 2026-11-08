# 评审 a8e055b（T-B03f：评审返修，0015）

- **结论：通过（附 M）**。可以推送（单独推会碰到 meta-json 枚举失败，和 83a031c 一起推就没问题）。下面的 M 是上生产前必须解决的，不阻断推送。

## 问题
- M1 冷却记录没有每小时清理：现在只在 PUT/DELETE 访问时清理（`licences/service.py:266-270`）。裁定：由 beat 调度、worker 每小时执行（plan 7.3 已写）——后端，等 beat 落地
- M2 裁定 D 未落地：`data_snapshots` 的 purpose CHECK 里没有 `horizon`，也没有“purpose IN ('candidate','plan','horizon') 时 user_id 必填”的 CHECK。裁定已把 candidate 加进去（plan 3.3）——后端写新迁移，迁移前先查违规行
- m1（T-O11 m1 未修）：`cli/delete_user_data.py:845-856` 的 `_maint_url` 在没有 URL 文件时会回退到环境变量——后端（工作区里有其他代理对这个文件的未提交改动，我没碰）
- m2（T-O11 m2 未修）：`:936-946` 仍然允许用 owner DSN 跑 dry-run——后端

## 已确认
保留期口径（`service.py:253-263`：有 paused_until 时以它为准；为 null 时 deleted_at+24h）与裁定一致；username 整键删除维持。

## 测试
ruff、mypy、静态检查通过；meta-json 枚举失败（继承自 0f8129b）；0015 在 0016 往返测试中降级和升级都正常。
