# POOL-T04：Windows 自检覆盖迁移预研

北京时间2026-11-11；文档单，不改三个自检或探针实现，不运行测试/探针、不连接数据库。事实冻结 `ds/T01=59d88a9aa8b3a2dd69ef7ee730af0ef5c99f940b`，代码冻结 `0ac8553d980db96d02eeada7c5acbe4258c53b8d`；主线祖先465e020。以下通过数字只引用T-01历史证据，不是本单新测结果。

## 结论与计数

AST只读盘点三个文件共56个参数化实例：history=17、offline=30、replay=9。T-01历史证据：Linux的history+offline共47通过；Windows的replay六项通过、B86两个模块平台skip。47不是Windows失败数，也不代表47项均依赖WSL路径：真正共同阻断是导入层`fcntl`，随后还存在POSIX权限/锁依赖。

- **当前直接可跑：6项**，全部来自replay，不需WSL/数据库；T-01已经覆盖。
- **最小拆分可新增：4项**，offline三项+history一项，无POSIX文件/数据库语义，但当前仍不能原样导入。先经后端授权重构可移植入口，再由测试迁移；不在测试里伪造fcntl模块。
- **可拆出的前置分支：至少3个原用例的局部断言**，不是3个完整新增通过用例，不与上面4项相加当覆盖成绩。
- 其余原B86全链路留Linux，replay另3项专库集成另派；不把Win ACL模拟当作Linux真实锁/0600验收。

## 当前可在Windows直接执行（6实例）

文件 `src/backend/selfchecks/test_tb70_replay.py`：

| node函数 | 实例数 | 依赖/意义 |
|---|---:|---|
| test_synthetic_manifest | 1 | 内存生成合成回放与确定性哈希，无外部数据 |
| test_positions_preview[utf-8/gbk] | 2 | 合成文件字节解析、编码与脱敏；不读券商真实文件 |
| test_migration_head_matches_checkout | 1 | 本分支迁移脚本图，Config不读ini；无数据库 |
| test_migration_head_rejects_non_unique_graph | 2 | 零头/双头合成负例；不连库 |

建议未来复验命令（本单未执行）：

```powershell
$env:PYTHONPATH = "$PWD\src\backend"
python -m pytest src/backend/selfchecks/test_tb70_replay.py -k 'synthetic_manifest or positions_preview or migration_head' -q -p no:cacheprovider
```

保留 no_network 守卫；现代码比较`socket.AF_UNIX`，当前T-01运行环境已支持该常量；若另一个Windows Python不支持，应另单将守卫写成只拒绝AF_INET/AF_INET6的可移植形式，不能通过删除守卫放行IP连接。

## 最小可迁移子集（4完整实例，当前仅候选）

| 文件/函数 | 现测试内部行为 | 原样不能跑的原因 | 建议迁移 |
|---|---|---|---|
| offline / test_no_budget_redistribution_and_deferred_defaults | 常量总额/分配约束+validate_response(200,合成列表) | 模块顶层fcntl | 将CAPS/TOTAL_CAP/EVIDENCE_PLAN与纯响应校验放进无POSIX导入的共用模块，原探针重导出保持兼容；测试迁到独立portable文件 |
| offline / test_offline_entrypoint_cannot_read_environment_or_files | main输出拒执行，并把open/getenv/Path.open替换为fail | 同上 | 将拒执行入口与纯控制层隔离；未来Win直测原真实入口，保留deny断言 |
| offline / test_plan_has_no_released_live_segment | EVIDENCE_PLAN全pending且与CAPS一致 | 同上 | 使用同一共用模块，不能把常量复制到测试里形成自证 |
| history / test_connection_never_reconnects | 构造HTTPSConnection但connect_attempts=1，在任何DNS/连接前抛no_reconnect | history与offline链式fcntl导入 | 将SingleConnection移入无POSIX导入的transport模块，由history复用；测试patch DNS/connect为fail，验证connect分支先拒绝 |

推荐先派“后端隔离纯模块入口+测试4项迁移”小单；要求原Linux47项保持原有断言全绿，Windows新增4项执行0skip，并分别报告。生产探针的POSIX锁/权限/台账代码不以Win兼容名义移除。

## 能拆分前置语义、但不能将原完整用例直接搬到Windows

- offline `test_default_disabled_and_main_no_side_effect`：segment未释放在`os.open`前拒绝、offline main退出2可移植；原例依赖ledger并混有账本未变断言。拆新例时用`tmp_path`缺省路径+把所有I/O替换为fail验证早退，保留原Linux整例，不复制假reservation实现。
- offline `test_stop_no_mutation`：STOP存在在`O_NOFOLLOW/getuid/flock`前拒绝，可在未来可导入入口下用临时合成STOP+临时计数原字节验证早退；不触达后续POSIX路径。它不证明全流程锁或持久化。
- history `test_cli_runtime_paths_still_require_explicit_authorization_flag`：无授权flag退出2的半条可拆；带flag的半条还经过`signal.SIGHUP`注册，Windows无该信号。可拆独立parser/dispatch逻辑后做零HTTP假execute验证，但不能把本单理解为真实调用授权。
- offline `test_bad_response_halts_entire_batch_and_redacts`八参数与`test_scalar_limit_codes_halt`四参数：原例均通过reservation并断言落账halted，属于Linux；未来可新增纯validate_response参数矩阵，但它是新增响应分类覆盖，不能替代这12条持久化/熔断证据。

## 必须保留Linux的原有例（完整列举）

offline：`test_durable_reservation_consumed_and_no_replay`、`test_nonblocking_lock_covers_dispatch`、`test_budget_no_reset_on_restart`、`test_unknown_counts_never_reset[4]`、`test_missing_counter_not_created`、`test_bad_response_halts_entire_batch_and_redacts[8]`、`test_untrusted_exception_not_saved_or_exposed`、`test_fsync_precedes_dispatch_and_second_stop_consumes`、`test_unsafe_counter_rejected_without_modification[3]`、`test_scalar_limit_codes_halt[4]`。连同上节两项早退原整例，均保留Linux原验收。

原因：reservation用`os.O_NOFOLLOW`、`os.getuid`、st_uid、0600、单链接、inode复验、真实非阻塞flock、fsync-before-dispatch。Windows的chmod并不等价于0600。尤其“缺文件失败”等宽泛HaltError断言可能由Windows缺少O_NOFOLLOW提前抛错而假绿，不能当作已到达指定分支。无需WSL绝对路径并不等于没有POSIX依赖。

history除上列connection与CLI局部分支外：`test_real_incomplete_notices_prevent_credential_access`、`test_six_synthetic_calls_have_locked_ledger_and_cleanup`、`test_failure_stops_all_later_interfaces_and_cleans[5]`、`test_transport_exception_never_renders_url`、`test_response_credential_echo_not_saved`、`test_existing_temp_file_never_overwritten_or_deleted`、`test_stop_no_credential_file_or_request`、`test_missing_authorized_environment_no_fallback`、`test_preflight_only_does_not_read_credential_or_dispatch`、`test_interrupt_also_cleans_and_consumes`、`test_http_limit_stops_before_response_body_read`均保留Linux全链路验收。

history的execute在证书/公告校验前调用inspect_counter，在finally也调用；inspect_counter依赖O_NOFOLLOW/getuid/0600/flock。因此即便STOP早退测试仍有finally依赖，不能仅看函数第一条分支声称可移植。完整公告路径另需固定`/usr/bin/pdftotext`；本文件多数执行用例是合成notice或mock，不把它们误写为已验证真实PDF来源。临时文件独占创建/权限和inode清理保持原约束。

## 真库冒烟的边界与后续另单前置

replay剩余3例：`test_snapshot_job_isolation_and_rollback`、`test_real_import_preview_confirm_dedup_rebuild_revert`、`test_cli_job`都依赖integration。固定`/tmp/tb70-pg-socket`与Redis Unix socket只是第一道障碍：fixture还会插入两个合成用户、登录、插入合成证券，测试会写快照、导入和回放作业。teardown仅关闭client/dispose engine，不承担整库数据清理；不是只读测试，**不能连用户库/共享库冒烟**。

若后续确需Windows专库测试：由运维提供专用PG/Redis、唯一测试身份与明确创建/销毁责任；后端确认loopback-only连接方案，测试核对require_isolated、冻结迁移唯一head、禁止IP外联守卫的受控loopback例外与清理计划后再执行。当前no_network拒绝所有IP，不能仅把DSN换成localhost后开跑；从不以属主身份绕过权限。此设施工作不包含在推荐4项纯逻辑迁移单中。

## 交付与验收建议

本单使用AST读取函数/parametrize数量与逐分支源码审查，无新pytest通过数字。下单建议：第一步后端只拆出纯控制/transport入口；第二步测试迁移4完整实例，补前置语义与响应分类反例；第三步Linux继续47原例、Windows已有6例+新增4例定点，分别冻结SHA和报告skip。数据库三例仍列阻塞，直到设施和清理责任另单齐全。
