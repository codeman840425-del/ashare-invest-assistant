# tests/fixtures/mairui —— 麦蕊响应录制样本（回放用）

> plan §2.1A / §6 / §8.0：本地与 CI 默认 `MAIRUI_MODE=replay`，`ingest` 读本目录（docker-compose.dev.yml 把
> `tests/fixtures` 只读挂到容器 `/fixtures`，`MAIRUI_REPLAY_DIR=/fixtures/mairui`）。**测试永不访问真实麦蕊**，
> `tests/conftest.py` 会在测试进程内拦截麦蕊域名解析。

## 硬约束
1. **不含 licence**：录制时 URL 中的 licence 段必须替换为 `***`（与网关日志规则一致），请求头/参数中也不得出现。
   `tests/replay/test_replay_example.py::test_tapes_contain_no_licence` 会扫描本目录。
2. **脱敏**：不含任何账户、股东代码、资金账号、姓名；只保留行情字段。
3. **再分发合规**（plan §7.1）：真实录制的行情数值是否可以入库，需等授权结论；在此之前只提交**合成样本**
   （目录名以 `_synthetic` 开头，文件内 `"_synthetic": true`）。
4. 每个录制集一个子目录，内含 `tape.jsonl`（一行一条响应）和可选 `README.md`（录制日期、接口、脱敏方式）。

## tape.jsonl 行格式（T-T01 约定，T-B 实现回放客户端时可扩展，不可删字段）
| 字段 | 类型 | 说明 |
|---|---|---|
| `t` | string(datetime, +08:00) | 响应时刻（回放时钟据此投放） |
| `endpoint` | string | 路径模板，licence 段写 `***`，如 `/hsrl/ssjy/all/***` |
| `params` | object | 除 licence 外的查询参数 |
| `status` | int | HTTP 状态（可录 429/503 以测退避） |
| `body` | any | 响应体（字段名以 T003 探测结论为准；合成样本字段名为占位） |

字段名【待 T003/T-B05 验证】，合成样本中的字段只演示结构，不代表麦蕊真实字段。
