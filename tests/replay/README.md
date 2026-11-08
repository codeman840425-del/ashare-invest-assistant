# tests/replay —— 盘中行情回放测试

> plan §8.0「回放（replay）」：录制的麦蕊响应（脱敏 fixtures）+ 时钟模拟，回放盘中一整天：刷新循环、陈旧判定、
> 翻转去抖、幂等 tick、通知合并、429/503 退避与预算。门槛：回放测试全过、无重复建议。

## 目录约定
```
tests/replay/
├── README.md
├── replay_kit.py              # FakeClock（可控时钟）+ Tape（读 tape.jsonl）+ ReplayClient（按时钟返回录制响应）
├── test_replay_example.py     # 示例：tape 合法性、无 licence、时钟推进、429 记录、陈旧判定示意
└── scenarios/
    └── <scenario>/scenario.json   # 一个回放场景：用哪个 tape、时钟起止、步长、期望
```
录制数据本身放在 `tests/fixtures/mairui/<录制集>/tape.jsonl`（与 ingest 回放目录共用，见该目录 README）。

## scenario.json 格式
| 字段 | 说明 |
|---|---|
| `id` | 场景 ID，如 `REPLAY-2026-11-02-full-day` |
| `tape` | 相对 `tests/fixtures/` 的 tape 路径 |
| `clock` | `{start, end, step_seconds}`，均为 `+08:00` 时间 |
| `expect` | 场景断言（如 `stale_after_seconds`、`max_suggestions_per_security`、`http_429_count`），由测试解释 |

## 规则
- 只读 fixtures，**绝不联网**；`tests/conftest.py` 拦截麦蕊域名，`MAIRUI_LICENCE` 强制为空。
- 时间一律用 FakeClock 注入，禁止在被测代码里直接 `datetime.now()`（实现方需提供时钟注入点，T-B 系列）。
- 同一 tape + 同一场景必须得到逐字节相同的输出（确定性）；需要随机数时固定种子。
- 新增真实录制前先确认 plan §7.1 授权结论；在此之前只用 `_synthetic*` 合成 tape。
