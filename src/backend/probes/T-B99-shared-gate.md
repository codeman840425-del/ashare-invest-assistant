# T-B99 共享门禁运行说明（北京时间 2026-11-09）

实现本身不授权部署或外呼；真实执行只由 Chief 当次派给运维。名单、证书验证、探针分别记账。

## 运维必须接齐的前置

- ingest 镜像包含 `app/ingest/shared_gate.py`，不依赖被镜像排除的 `probes/`。探针从同一版本工作树运行；直接 `python run_all.py` 也会导入这份模块，至少 Python 3.11。
- 在 WSL/Linux 原生文件系统上准备**唯一**共享状态目录，绑定到 ingest 和两个探针进程；各自的 `MAIRUI_SHARED_STATE_DIR` 必须指向该同一物理目录。禁止用两个副本、Docker 临时层、独立 volume 或未验证锁语义的 Windows 目录替代。
- 目录不得为软链接，POSIX禁止other权限；建议0700，所有写入者使用同一受控POSIX UID（新状态文件固定0600，只有同组不足以互读）。挂载只给ingest与授权探针；api/worker/普通用户不挂载，不提供清闩API。运维须核实容器与WSL实际UID/读写权限，不可chmod 777。
- 运维从无密文状态视图核对探针环境证书与本人库内证书为同一项，仅把非秘密 UUID 绑定到 `MAIRUI_SOURCE_LICENCE_ID`；不得输出、存储证书/HMAC/密文作核对。
- 运维安装非秘密 `policy.json`，不是由应用自动初始化。schema 固定 `mairui-shared/v1`，`egress_ip` 为当次批准的唯一出口，`licences` 以证书 UUID 为键，每项含正整数 `per_minute_limit`，不得高于该证书既有档位/管理员覆盖。产品取 policy 与数据库上限的较小值；探针扣同一文件账。

合成结构示例（不是执行授权，不含真实标识）：

```json
{"schema":"mairui-shared/v1","egress_ip":"192.0.2.10","licences":{"00000000-0000-4000-8000-000000000099":{"per_minute_limit":150}}}
```

- ingest 仍禁止全站 `MAIRUI_LICENCE` / `APP_MASTER_KEY`；产品只在门禁通过后从原 HPKE vault 解开本人证书。探针按既有安全接入方式临时读环境证书。
- 仅在批准后设置 ingest `MAIRUI_MODE=live`、启用既有设置页证书开关；dev compose 的 replay 覆盖需由运维当次调整。名单还必须有既有只读授权回执、已覆盖的交易日日历、有效本人证书。只改 mode 不产生授权。
- 名单固定北京时间交易日 18:00 至 23:59:59，一批三 HTTP，端点各一次，完成至下一开始至少 60 秒；失败/预留不退数，不跨日补打。名单回执与调度/outbox 复用既有路径。
- T-B99b：验证另需 `/run/aia/authorizations/mairui-verification.json`，父目录/文件沿用 root-owned、不可组写、文件0444门槛。字段严格为 `kind=mairui_licence_verification`、本人 `user_id/licence_id`、唯一 `receipt_id`、带时区 `not_before/expires_at`、`max_http_requests=1`；过期、换人/换行、次数非1均拒绝。按 receipt_id 持久预留一次，多个验证意图不能叠加。只有名单三次回执时，队列和pending扫描都不验证；验证仍需独立当次明确授权，不占名单三次/探针128。
- 验证继续消费既有 `verify_licence` 与pending漏投兜底，调用 `/tcalendar/list/{year}/`；发送前重新检查回执、全局暂停、本人证书/账号/管理员hold。名单也逐请求重查Redis全局暂停、18:00窗口、日历和本人状态；Redis不可用即闭锁。
- 真实 T-B05 必须做既有 `--check-egress` 并得到稳定出口；未确认出口不能预留麦蕊请求。T-B86 还保留原官方证据、128 分项台账、临时凭据 0600/清理等全部门禁。

## 停机与人工恢复

- 公共 `STOP` 停所有证书；历史STOP在两个真实入口的提前退出前也映射公共STOP。写入固定脱敏标记并flush/fsync文件与POSIX目录，不复制旧STOP内容。
- T-B99b：103/429、分钟账改按证书内容导出的私有不透明标识定位，UUID仅作策略/归属及 `.binding.json` 映射；所有四类真实发送均须先确认该绑定。删重设同证书换UUID后继承原halt和分钟账，IP超限一小时次数也跨这些UUID累计；标识、绑定、分钟账不进入API/报告，不得通过删除绑定或换目录重置。
- 未迁移的旧UUID halt保留并保守闭锁，旧UUID未知在途/最近一分钟账也闭锁，交授权运维核清，不能自动丢掉历史闩锁以启用新格式。显示的120秒/一小时暂停到期仍不会清持久闩锁。
- `single-egress.lease.json` 是 `ingest:single-egress` 文件互斥。探针优先标记只在争锁阶段使用；正常请求完成才清除逐证书 `requests.json` 的 inflight。未知在途保留租约、预留和 halt，进程重启也不重放。
- 历史 `master_runs.stats.upstream_halted` 保留为事实；后续停机范围以共享证书闩锁为准，避免旧历史永久阻塞其他证书。原 `results/STOP`、名单 HALTED、T-B86 原台账 halted 仍须检查；T-B05 发现旧 STOP 会映射成公共 STOP，不能通过迁移目录绕过。
- 只有 Chief/授权运维在当次明确指令下核实两侧停止、距最后请求至少 60 秒、唯一出口、未知在途已核清后，才能清相关 STOP/证书 halt/未知 lease/旧侧闩锁。不得删除请求账/探针计数或改失败批次以续跑；本实现无自动 reset/初始化命令。
- 产品侧心跳把探针 halt 投影为原证书状态和站内通知；按同一 halt UUID 去重。全局 STOP 只通知管理员。SSE `data_licence` 仅四字段：status、verification_id、last_error_code、at。

## 本地验证边界

专用 PostgreSQL/Redis、合成 HPKE/用户/日历/时钟/HTTP，未读取用户库证书、未真实外呼、未改变运行栈。Linux 验证保留真实 0600/O_NOFOLLOW 文件路径；Windows 未为测试放宽生产凭据门禁。

申请新任务：由 Chief 安排复核、定点测试与运维挂载/授权后执行；实现不包含日 K 或实时链路。
