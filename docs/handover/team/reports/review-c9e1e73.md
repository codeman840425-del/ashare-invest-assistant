# 评审 c9e1e73（T-B47：CSRF 双提交、Idempotency-Key 头、/horizon-assessments、/admin/ingest/status）

评审人：架构师 · 2026-11-01（America/Denver）· 方式：只读，`git archive c9e1e73` 导出到 /tmp/rv-c9e，在干净副本中运行；未改动工作区。

## 结论
**有条件通过**：没有 B 级问题。CSRF 双提交与 `Idempotency-Key` 头的实现正确，可以合入。有 3 个 M 级问题，需要后端按 T-B46-47-rulings.md 的 R8、R10 修复：/admin/ingest/status 的多个口径与契约不一致；/horizon-assessments 不落库，返回的 `snapshot_id` 在库中查不到；两个新端点没有 response_model。分类器所需的 `f.*` 尚未接入，所以所有证券都被 `data_missing` 封顶。这一点不算本单缺陷，按 R9 另立 T-B30a。

## 问题清单

### M（必须修）
| # | 位置 | 问题 | 要求 |
|---|---|---|---|
| M1 | `src/backend/app/licences/ingest_status.py` 第 83–104 行（`_leader`） | 只按 `ended_at IS NULL` 取租约，不判断是否已过期；租约过期但没写 `ended_at` 时，仍把旧持有者当 leader 返回，`lease_expires_at` 是过去的时间；没有租约时返回各字段为 null 的对象 | 按 R10：只认 `lease_expires_at > now` 的租约；没有时 `leader: null`（契约 #27 ⑨） |
| M1 | 同文件第 149–176 行（`build`） | ① `budget.per_minute_limit` 和 `queues[].depth` 是对截断后的 `licences[]`（≤500 行）求和，超过 500 张证书时会偏小；② `freshness` 固定返回 `[]`；③ 没有 `alerts[]` | 按 R10：预算与队列深度直接对全部 `active` 证书聚合，不经 `licences[]`；`freshness` 固定 6 行，按契约 §7.9 阈值判断；按 plan 6.1 `admin_alerts` 生成 `alerts[]` |
| M1 | 同文件第 107–114 行（`_oldest_queued`） | 只看最近 1 天入队的任务，入队超过 1 天还在排队的任务会被漏掉，正是最该告警的情况 | 去掉回看窗口（可加 `status='queued'` 的部分索引），空队列为 0 |
| M2 | `src/backend/app/api/v1/horizon.py` 第 21–57 行；`app/strategy/horizon/inputs.py` 第 160–168 行 | 只计算不落库；`snapshot_id` 是输入的 UUIDv5，`data_snapshots` 中不存在，违反契约 #27 ⑧（`snapshot_id` 必须是 `data_snapshots` 中真实存在的 id）；格式合法但不在主数据中的代码不返回 404 | 按 R8：读最新记录，没有或已过期时同步计算并写入 `symbol_horizon_assessments`（`trigger=on_demand`）和 `data_snapshots`（`purpose='horizon'`、`user_id`，用到证书数据时带 `licence_id`），返回真实快照 id；Query 加契约 pattern；未知代码返回 404 |
| M3 | `horizon.py` 第 21 行、`api/v1/admin.py` 第 219 行 | 两个端点返回 `dict[str, Any]`，没有 `response_model`，OpenAPI 中没有响应 schema，schemathesis 无法校验响应结构，前端也无法生成类型 | 补 pydantic 响应模型（`HorizonAssessment`、`IngestStatus`，`alerts` 与 `leader` 可空按契约） |

（M1 的三行是同一个问题：ingest/status 口径不符。）

### m（建议修）
| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `inputs.py` 第 11–12 行 | 除主数据派生的少数键外，`f.*` 全部为 null，所有证券都因 `data_missing` 封顶，`suitable` 恒为空 | 不在本单修。按 R9 由 T-B30a（依赖 T-R11）接入；前端在 `inputs_missing` 非空时展示“数据不足”，不要显示成“都不适合” |
| m2 | `inputs.py` 第 99 行 | `f.is_st` 已把 `delisting` 算进去，与 R9、问题 77 一致 | 无需改，补一条单元测试锁定 |
| m3 | `api/v1/horizon.py` 第 26 行 | `security_code` 只限长度 1–16，schemathesis 生成 15 位数字时得到 400 | 按 R11 第 2 项改用契约 pattern |
| m4 | 带登录态的 schemathesis | 12 个 ST202 | 逐项处理见 R11 |

## 逐项核对（通过项）
- CSRF：`app/auth/sessions.py` 第 11–55 行（`csrf_ok`）。写请求同时校验 `X-CSRF-Token` 头、`csrf_token` Cookie 与会话令牌，三者一致才放行，用 `hmac.compare_digest`；`csrf_token` Cookie 不是 HttpOnly，SameSite=Lax（`api/v1/auth.py` 第 128、141 行），与契约一致。这符合契约 §1.3 和 v0.2.4 #13。测试员的 strict xfail 两例已转为 XPASS(strict)，报成 FAILED，原因在这里，不是缺陷。
- `Idempotency-Key`：`app/common/idempotency.py` 第 34 行改用 `Header(alias=...)`，长度与非空校验进 OpenAPI；格式错误返回 `400 VALIDATION_ERROR`（`field: "Idempotency-Key"`），与契约 §1.2 一致。
- /admin/ingest/status：不返回证书值、密文、HMAC；`egress_ip` 只给掩码；需要管理员权限（`AdminDep`）。
- 无硬编码密钥；新代码没有日志打印证书或 IP 全文。

## 测试结果
| 项目 | 结果 |
|---|---|
| ruff check / ruff format --check / mypy（98 个文件） | 通过 |
| `scripts/ci/check_contract.py --meta-json`（c9e 的 /meta/enums） | 2 项失败，都是已知的 v0.2.9 未实现项（版本号 v0.2.8；缺 T-A11 的 4 个枚举）。用本次修订后的契约（提交 4532478）对照，结果相同，没有新增差异 |
| `scripts/ci/check_code_namespaces.py` | 通过 |
| 测试员用例（tests/backend + tests/replay，后端 venv，Docker 可用），跑了两次 | 第一次：5 failed、880 passed、94 skipped、55 xfailed、7 xpassed。第二次：3 failed、880 passed。两次的失败都是：CSRF strict xfail 两例 XPASS(strict)（已实现，测试员去掉标记），另有 `test_contract_live` 的子用例，即带登录态的 schemathesis 遇到 `GET /accounts` 的 `INVALID_CURSOR`，每次随机种子不同，个数也不同，按 R11 加例外。没有真实回归 |
| schemathesis 4.33.0（未登录） | 全部通过 |
| schemathesis（带登录态，排除 logout/password） | 12 个 ST202，见 R11 |
| gitleaks（提交区间） | 0 命中 |

## 谁要做什么
- **后端**：T-B47-x 修 M1–M3、m3（按 R8、R10、R11）。T-B30a 另立，排在 T-R11 之后。
- **测试员**：去掉 CSRF strict xfail 与 register-closed xfail；schemathesis 配置按 R11 加例外；`/horizon-assessments` 加用例：同一输入两次请求返回同一 `snapshot_id`，且该 id 在 `data_snapshots` 中存在，未知代码返回 404。ingest/status 加用例：租约过期时 leader 为 null、`freshness` 固定 6 行、`alerts` 不为 null。
- **前端**：写请求带上 `csrf_token` Cookie 与 `X-CSRF-Token` 头；采集状态页显示 `alerts[]`；周期评估在 `inputs_missing` 非空时显示“数据不足”。
- **研究员**：T-R11。
