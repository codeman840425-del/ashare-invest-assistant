# T-A52 裁定：风控「清除覆盖」接口（DELETE /risk-controls/{control}，架构师，北京 2026-11-09）

> 状态：裁定生效（用户已定方向 A：正式接口；B 直改库已否决）。基线 team-b=e12bef9。本文定契约，不写实现；实现与测试见 §7–§8，转 Chief 派单（后端 T-B95、测试随单）。
> DeepSeek：未用，原因：裁定不外包。

## 0. 问题与输入

T-O41 核查（docs/handover/team/reports/T-O41.md）：PUT /risk-controls 只 upsert `scope='user'` 行并追加历史；**写回默认值仍保留 user 行**，文件默认未来变化不再继承，且无任何清除覆盖、恢复继承的入口。测试 T63 因「缺无损恢复来源的接口」阻塞。用户裁定方向 A：后端新增正式「清除覆盖」接口；B（运维脚本直改库）否决。

## 1. 既有权威条款（依据）

| 条款 | 出处 |
|---|---|
| 继承链：文件默认（`config/risk_controls.yaml`）→ system 行 → 本人 user 行；plan §2.5.6「系统默认 → 用户覆盖」 | `app/suggestions/risk.py:438-465`；plan L756 |
| 现行 PUT：整批校验通过才写（原子）、advisory lock 串行、每次变更追加 `risk_control_settings_history` + 审计 `risk_control.updated`、幂等（同值跳过）、返回六项有效设置 | `app/risk/settings.py:89-210`；契约 §7.11.2 |
| CSRF：非白名单 DELETE 双提交校验，缺失/不符 403 CSRF_FAILED；判定顺序 ③认证 ④CSRF ⑤…；无会话写请求 401 | 契约 §1.3（v0.2.9 #30）、`app/auth/deps.py:142-178` |
| 表：`risk_control_settings`（UniqueConstraint scope×user×行）；`risk_control_settings_history`：`setting_id` NOT NULL FK、只追加 | `db/tables/strategy.py:213-243` |
| position_cap 画像继承：无 user 行时 profile `max_single_position_pct` 覆盖 single_position_max_pct，`source` 仍 user | `risk.py:458-465`、`settings.py:74-76`；T-O41 边界① |
| GET/PUT 形状：六项 `[{control, enabled, params, source, default}]`，`default` 只读 | 契约 §7.5/§7.11.2、T-A26 |
| 全仓无写 system 行代码，system 行实际恒无 | T-O41 现状① |

## 2. 契约

### D1｜路由与语义

`DELETE /api/v1/risk-controls/{control} 🔒`，`control ∈ risk_control` 六枚举。语义 = **删除操作者本人该 control 的 `scope='user'` 行、恢复继承**（回退到 system 行 → 文件默认），**不是删除配置本身**：六项控制恒存在、恒可评估，被清除的只是本人的覆盖值。system 行与文件默认**不可通过本接口删除或改动**（权限边界，见 D4）。幂等键不变：scope×user_id×control。

**路径形状**：本接口不设 `/risk-controls/{control}/…` 之外的变体；URL 参数只有 `control` 一个，不提供 `?scope=` 或 body——**接口形状本身只允许定位「本人 user 行」这一种资源**，system 行无资源路径可寻址，杜绝「普通用户经变体路径触达 system 行」的整类风险。

### D2｜响应：200 + 完整六项有效设置（与 GET/PUT 同形）

- 返回 `200 list[RiskSetting]`（六项，含 `source`、只读 `default`），语义与 PUT 一致：**删除即刷新后的有效设置**，前端一次调用即可刷新表单。选 200 而非 204：PUT 先例（返回六项）、前端可直接替换本地状态、幂等重放时也有可比对的状态快照。
- 清除后该 control `source` 变化（user 行存在 → `user`；清除后 → `system`，除非 profile 命中，见 D7）。
- **不返回 404-on-missing**：无本人覆盖时重复清除 → `200`，六项照常返回，状态不变、无新增副作用（幂等）。项目「资源归属 404」针对「他人/不存在的资源」，此处删除的目标资源（本人 user 行）在无覆盖时本就不存在，语义是「确保无覆盖」这一幂等终点态，与 strategy-instances confirm/pause/resume「目标态即当前态返回 200」同一先例。

### D3｜鉴权、CSRF、限速与判定顺序

- `AuthDep` 本人鉴权：无会话 → `401 AUTH_REQUIRED`；账号非 approved → `403 ACCOUNT_NOT_APPROVED`（§1.3 ③）。
- CSRF：双提交校验，缺失/不符 → `403 CSRF_FAILED`（§1.3 ④，白名单只有 login/register，DELETE 不在白名单）。
- 限速：不另设接口级限额，沿用全站 429 规则。
- 判定顺序沿 §1.3 v0.2.9 #30：① 限长/限体 → ② 路由/方法（未知 control → `404 NOT_FOUND`，路径不存在同类）→ ③ 认证 → ④ CSRF → ⑦ 端点自身判断。框架解析不得先于 ③④。

### D4｜权限边界：只删本人 user 行；system 行不可触碰（用户裁定）

1. DELETE 只作用于 `scope='user' AND user_id=操作者本人` 的行。**system 行与文件默认一律不可通过本接口删除或改动**。
2. 普通用户对 system 行**无任何写/删路径**。任何试图触达 system 行的请求形状（`?scope=system` 查询参数、body 携带 scope/目标 user、其他变体路径）→ **`404 NOT_FOUND`**，理由：本接口可寻址资源只有「本人 user 行」一种，变体形状不构成资源定位，按不存在处理，与 §1.3「`/admin/*` 隐藏存在性 404」同一风格，不提供 403 探测面（403 会向未授权者确认「该资源存在但无权」，本接口根本不存在那种资源形状）。system 行的管理入口是**独立的管理员功能**，不在本契约范围；未来若立，须另走契约与 G7/管理员鉴权设计，不得复用本接口。
3. 不设管理员跨用户重置（T-O41 同）；如需，另立管理员接口。
4. 审计 `risk_control.reset` 写清操作者身份，供核对「只有本人动本人」（见 D6）。

### D5｜幂等与并发

- 幂等终点：**「本人对该 control 无覆盖」**。无覆盖时重复 DELETE → 200、状态不变。删除已不存在的行不是错误。
- 并发：与 PUT 共用既有 `pg_advisory_xact_lock(hashtextextended(owner,202602))` 串行（同 owner 的 settings 写路径互斥）；DELETE 内先取行级锁（`with_for_update`）再删，与 save() 同模式。串行化异常按全站 409 重试语义处理。
- **对其他 control 无副作用**：只删 {control} 指定的一项，绝不批量。

### D6｜存储方案：选 ①（override_active 标志），迁移 0028

**裁定：方案 ①**——`risk_control_settings` 加 `override_active boolean NOT NULL DEFAULT true`，清除置 false；`effective_config` 与 `entries` 的 user 行读取一律加 `override_active=true` 过滤；历史照常追加。理由：

1. **保 append-only 与 FK**：方案 ②（物理 DELETE + 历史 setting_id 可空/去 FK）要动 `risk_control_settings_history.setting_id` 的 NOT NULL 与 FK 约束、并给 append-only 触发器开洞，违反「历史只追加」的最小惊讶设计；方案 ① 表结构演进最小（一列 + 默认值），历史与 FK 完整保留。
2. **审计链不断**：历史行继续指向上一个 setting_id，重置事件（D6 审计）与后续覆盖变更在同一条链上可追溯。
3. **实现面小**：PUT save() 的 upsert 语义不变（更新时 `override_active` 恒置回 true——重新覆盖即恢复）；effective_config 加一个 where 条件。
4. 反向理由（方案 ② 的物理删）唯一优势是表行数少，但每用户至多 6 行，量级可忽略。

**迁移注意（0028）**：`ALTER TABLE app.risk_control_settings ADD COLUMN override_active boolean NOT NULL DEFAULT true`（单语句加带默认列，PG11+ 不重写表）；**不**改 history 表、不动触发器；默认 true 保证存量行语义不变（全部视为有效覆盖）。迁移可逆（drop column）。

### D7｜position_cap 与 profile 交互（继承终点）

清除 position_cap 的 user 行后：`effective_config` 无 user 行 → profile `max_single_position_pct` 生效（非 null 时），`source=user`（来源是本人画像）；profile 无值 → 文件默认，`source=system`。**契约措辞是「回到继承」而非「回到文件默认」**——继承链终点可能落在 profile，前端按返回的 `source`/值展示，不自行推断。其余五项无 profile 交互，终点恒为 system 行（现状无）→ 文件默认。

### D8｜审计与历史

- 审计：`risk_control.reset`，`actor_id=操作者本人`（AuthDep 会话用户）、`actor_role=会话角色`、`target_type=risk_control_setting`、`target_id=被清除的 user 行 id`、`detail={control, history_id, had_override: bool}`（had_override=false 时 target_id 为 null，仍记审计——重置意图本身可审计）。
- 历史：`risk_control_settings_history` 追加一行 `enabled=null, params=null, changed_by=本人`（append-only 表的既有可空列，语义「清除」）；`setting_id`=被清行 id（方案 ① 行仍在，FK 稳）。幂等重放（无覆盖）**不**追加历史、**不**写审计，避免审计噪声——与 PUT 同值跳过同例。
- 核对口径：审计中 actor 与被清行 user_id 必须一致（只有本人动本人）；任何 actor≠行属主的写路径都是缺陷。

### D9｜负例集（测试照此写）

| # | 场景 | 期望 |
|---|---|---|
| N1 | 未登录 DELETE | 401 AUTH_REQUIRED |
| N2 | 登录但缺/错 CSRF | 403 CSRF_FAILED |
| N3 | 未知 control（/risk-controls/nope） | 404 NOT_FOUND |
| N4 | 清除无本人覆盖的 control | 200，六项返回，system/文件默认不受影响，GET source 回 system |
| N5 | `?scope=system` 或 body 带 scope/user 变体 | 404 NOT_FOUND（D4.2，不确认资源存在） |
| N6 | 已登录非本人操作路径（如携带他人 user_id 参数） | 404（接口不寻址他人资源；本接口无跨用户参数面） |
| N7 | 账号非 approved | 403 ACCOUNT_NOT_APPROVED |
| N8 | 并发 PUT+DELETE 同一 control | advisory lock 串行，终态一致（无半写/双历史） |
| N9 | 清除后 GET/PUT/求值链路 | effective 回继承值；PUT 再覆盖 → override_active 回 true |
| N10 | 历史与审计 | 每次真实清除恰一行 history + 一条 risk_control.reset；幂等重放零追加；actor=行属主 |

### D10｜T63 解除阻塞的验收标准

1. 有覆盖 → PUT 改值 → DELETE → GET：值回继承终点（profile 或文件默认），`source` 相应变化，六项完整。
2. N4 幂等：DELETE 两次 → 第二次 200 无副作用（无新 history/审计）。
3. 前端可在 /risk-controls 页对单项执行「恢复继承」，T63 的「无损恢复来源」即本接口；浏览器侧 UI 验证归测试（浏览器可用后）。
4. 求值链路（候选信号/evaluation）在清除后立即用继承值，无需重启。

### D11｜契约同步（api-contract.md）

- §7.5 路由表加一行：`DELETE /risk-controls/{control} 🔒`。
- §7.11.2 加一段 T-A52 裁定（语义、幂等、权限边界、存储、审计、T63 验收）。
- §7.11.2 错误码补：404（未知 control）、403 CSRF、401、幂等 200 说明。
- OpenAPI/前端类型/客户端 mock 随 T-B95 实现同步。

## 3. 不兼容点

- 契约层：无字段/枚举变更；新增一个端点（加法）。
- 存储层：迁移 0028 加列（默认 true，存量语义不变），可逆；不改 history 表。
- 行为层：`default` 键语义、继承链、PUT 行为均不变。

## 4. 受影响任务

- T-B95（后端，Chief 已预告）：实现 DELETE + 存储方案 ① + 迁移 0028 + 定点用例（N1–N10 按需裁剪）。
- 测试：T63 负例与幂等断言随 T-B95 验收（T63 解除阻塞以 D10 为准）；浏览器 UI 验证待环境。
- 前端：/risk-controls 页「恢复继承」入口（另行派单，非本契约阻塞项）。
- 运维：无（不动部署；迁移随 T-B95 发版）。

## 5. 例外汇总

| 例外 | 内容 |
|---|---|
| 无覆盖清除 | 幂等 200，不 404（D2） |
| system 行变体路径 | 404 隐藏存在性，不给 403 探测面（D4.2） |
| 幂等重放 | 不追加历史/审计（D8） |
| position_cap 终点 | 可能落在 profile（source=user），措辞「回到继承」（D7） |
| had_override=false | target_id=null 但仍记审计（D8） |
