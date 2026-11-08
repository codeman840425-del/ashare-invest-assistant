# T-O11 评审裁定（M2 主密钥按服务）及 T-B03f / T-B10 / T-R11 补充裁定

- 作者：项目架构师；日期：2026-11-01（America/Denver）
- 落地提交：`e56462c`（仅 `docs/plan.md`、`docs/api-contract.md`；契约版本号不升，变更表加 v0.2.9 #29）
- 依据：当前代码（`src/backend/app`）、`docs/strategies/feature_spec.md`、`T-B03f.md`、`T-B10.md`、`T-R11.md`、麦蕊公开文档（**未用任何证书调用接口**）

## 1. M2：`APP_MASTER_KEY` 按服务分配（plan 1.3）

| 服务 | 用途（代码位置） | 需要 | secret 文件 | 启动检查（非 local/test） |
|---|---|---|---|---|
| api | 游标签名 `common/pagination.py:42`；邀请码 HMAC `auth/invites.py:61`；登录 IP HMAC `auth/deps.py:111`；证书去重与冷却指纹 `licences/seal.py:77-93`（`licences/service.py:288,311` 调用）；导入文件密钥 `importing/keys.py:24`、`storage.py`；LLM 密钥密文 | 需要 | 挂载 | 缺失/不足 32 字符拒绝启动 |
| worker | 现为占位；规划：导入解析、LLM 网关解密 | 需要 | 挂载 | 同 api |
| ingest | 只用 X25519 证书私钥 | 不需要 | 不得挂载 | 不要求；检测到主密钥则拒绝启动 |
| beat | 只调度 | 不需要 | 不得挂载 | 不要求 |
| signal-rt | 不签游标 | 不需要 | 不得挂载 | 不要求 |
| maint-cli | 只按 user_id 删行/文件/Redis 键；连接串读 `AIA_MAINT_DATABASE_URL_FILE` | 不需要 | 不得挂载 | 不要求 |
| migrate | 不算 HMAC | 不需要 | 不得挂载 | 不要求 |
| nginx/postgres/redis 等 | — | 不需要 | 不得挂载 | — |

- 后端：Settings 的强制检查只对 `SERVICE_NAME ∈ {api, worker}`；缺省按 api；白名单外未知值在非 local/test 下拒绝启动。所有派生密钥函数在非 local/test 下取不到主密钥必须抛错，不退回临时密钥。ingest 发现主密钥拒绝启动。
- CI 规则 7：`check_secret_boundary.py` 写死一张显式白名单表（api、worker 必须挂；表中其余服务必须不挂；compose 出现未登记服务 → 失败）。现状 `MASTER_OWNERS=("api","worker")`（:54-56）方向一致，但要改成“每个服务显式登记”。
- 升级约束：① 升级不得自动生成；仅全新部署（无 secret 文件、无旧值、空库）可生成；② secret 缺失 + 旧 `.env`/环境有非占位值 → 迁移到 600 文件，不打印；③ 两者都无但库有数据（`app.users`/`app.invite_codes`/`app.user_data_licences` 任一非空）或连不上库 → 拒绝启动；④ 两处都有且不一致 → 拒绝；⑤ 轮换不在 V1。
  - 核对：运维已提交 `1cf643e`（“已有→用；旧 .env→迁移不删；库有数据→拒绝；仅全新空库生成”），方向与本裁定一致；④“两处不一致拒绝”与“连不上库拒绝”需运维确认已覆盖。

## 2. `aia_maint` 列级原则（plan 7.3 第 7 条）
不得 SELECT 密文列与 `users.password_hash`；不得 UPDATE `users.role`；SELECT/UPDATE 按列授予，DELETE 只对清单内表。后端在 CLI 中维护“表 → SELECT 列 / UPDATE 列 / DELETE”清单交运维；运维用列级 GRANT 实现，`verify-roles.sh` 用 `has_column_privilege` 断言。

## 3. T-B03f 未决项
| 项 | 裁定 |
|---|---|
| 冷却记录保留期 | 有 `paused_until` → 保留到 `paused_until`（不另加 24h 上限）；null → 删除后 24h。删除了 plan 中“两者以先到者为准”的歧义写法。a8e055b `service.py:253-263` 与此一致，不用改 |
| 审计 detail 的 `username` 整键删除 | 维持整键删除（从严）；以后审计 detail 不写 username，用 id |
| 每小时清理 | 由 beat 调度、worker 执行；在此之前只靠访问时清理和读取时视为不存在。上生产前必须有，记为 a8e055b 的 M，不阻断推送 |
| 裁定 D | 表 CHECK 改为 `purpose IN ('candidate','plan','horizon')` 时 `user_id IS NOT NULL`（加入 candidate），并把 `horizon` 加进 purpose CHECK；后端新迁移实现，迁移前先查违规行。83a031c 写 candidate 快照时已带 user_id，不受影响 |
| T-O11 m1/m2（`_maint_url` 回退到 env；owner DSN 可跑 dry-run） | 维持原评审：CLI 只认 `AIA_MAINT_DATABASE_URL_FILE`；dry-run 只能用 aia_maint 或只读连接 |

## 4. T-B10 未决项
| 项 | 裁定 |
|---|---|
| RC4 行业 | 麦蕊 `/hszg/zg/{code}`（每周六 11:00）+ `/hszg/list`（每周六 03:05）；备选 `/hslt/primarylist`、`/hslt/sectors`（每周六/每日 16:20）。表：按证书的行业归属表，带 `source_licence_id`，表名由后端在 T-B43 定【待定】；一级代码格式【待核实】；采集方 ingest，周更。接入前 RC4 必须出 gap（83a031c 未出，记 m） |
| 停牌 | 日 K `sf`（1 停牌）随日 K 采集；补充 `/hitc/jrts` 的 `tp`（每日 15:40）。落库为日 K 停牌标记或 `market_events` 新增 suspension 类型，T-B43 定【待定】；ingest 日更；【待核实，T-B05】 |
| ETF 类别 | 麦蕊文档只有“基金-ETF基金行情/净值”大类，没有子类【待核实】；备选交易所公开基金列表分类【待核实】。**所有 ETF 在 `t0_round_trip.data_source` 接入前一律 T+1**（plan 2.13 新增行；契约 v0.2.8 #9 改写）。07b8d74 符合，无 M；但 `fund_t_plus` 在 data_source 为 null 时传入类别仍可能返回 0，必须以 data_source 非空为闸门（m） |
| `planned` 状态展示 | 前端必须显示（只读，不可再决定） |
| 0016 在共享库上执行 | 运维先执行重复查询 `SELECT user_id, security_code, count(*) FROM app.research_candidates WHERE status IN ('researching','watching') GROUP BY 1,2 HAVING count(*)>1`；有结果先人工处理。实测：有重复时 0016 报 UniqueViolation，整个 upgrade 回滚，不会留下半截状态 |
| `_RISK_TEXT["delisting"]` 文案 | 后端改为“退市整理”（`content.py:53`）；`star_st` 才是“退市风险警示” |
| ETF/指数建候选的状态码 | 契约是 **400** VALIDATION_ERROR（`issue=security_type_not_supported`），实现也是 400；“422”的说法与契约不符，以契约为准 |
| listing_status `delisted`/`missing_from_list`（feature_spec §10.2 待架构师定） | T-B30a 对这两种状态输出全部为 null，分类器按现有 `data_missing` 封顶；不新增拒绝路径，不改契约 |

## 5. T-R11 / feature_spec §13
| 项 | 裁定 | 落地 |
|---|---|---|
| C1 | 15 个 `f.*` 定义以 `feature_spec.md` 为准；`horizon_classifier.md` 附录只放指针；裁定 R9 的“写在附录”被取代 | plan T-R11 行 |
| C3 | 分类器 `rank_pct_universe` 是因子池排除规则的例外：不排除 ST/*ST/退市整理，只要求上市满 20 个交易日（并排除北交所与停牌），定义见 feature_spec §1.4 | plan 2.12.1 |
| C5 | 导入器保持严格：规则单位必须与 feature_catalog 完全一致，不做 sign 兼容；SH5/SW2/SW3 改 `unit: pct`、阈值 0 | plan 6.1 分类器配置块已同步 |
| C8 / 问题 76 | `user.avg_holding_days` 按证券计算，只统计本人该证券的已平仓批次；365 天、FIFO、数量加权、少于 3 批次为 null 不变；仍是【默认执行，用户可改】 | plan 2.5.3 用户输入口径、第 9 节问题 76 |
| 问题 77 措辞 | 契约 §3 只列了值与优先级（`delisting > star_st > st`），这次补上含义：`star_st` = *ST = 退市风险警示，`delisting` = 简称带“退”的退市整理标记，`listing_status=delisting_period` 是上市状态。结论不变：`f.is_st` 仍包含 star_st 和 delisting，分类器仍封顶 | plan 2.5.3、问题 77；契约 §3 与变更表 #29 |
| “退市风险警示”全文检查 | plan 共 3 处：2.5.3、问题 77 已更正；4.x 公告事件类型里的“退市风险警示”用法正确，保留。契约原文没有这个词 | — |
| §13 其余建议值 | 全部采纳：覆盖率 0.75、组内 N≥5、σ 至少 15 个收益、fin_report 法定披露日估计，以及 A1–A4。特征定义归研究员 | — |
| 冲突检查 | 与契约和 plan 都没有冲突。plan 原有的“因子池排除”和 T-R11 行“附录”这两处已按 C3、C1 改掉 | — |

## 6. 谁要做什么
- **后端**：① Settings 按服务检查主密钥、派生函数不退回临时密钥、ingest 发现主密钥拒绝启动；② 新迁移：data_snapshots 的 purpose 加 `horizon`，并加 CHECK（candidate/plan/horizon 时 user_id 必填）；③ `content.py:53` 文案；④ `fund_t_plus` 以 data_source 为闸门；⑤ RC4 行业缺失要出 gap；⑥ 提供 aia_maint 列清单；⑦ T-B43 设计行业与停牌表；⑧ CLI 只认 maint URL 文件、dry-run 不用 owner DSN；⑨ beat/worker 每小时清理冷却记录。
- **运维**：① CI 规则 7 改显式白名单（`check_secret_boundary.py`）；② 核对 1cf643e 已覆盖“两处不一致”与“连不上库”两种拒绝；③ grants.sql 列级授权与 verify-roles 断言；④ 在共享库执行 0016 之前先跑重复查询。
- **研究员**：① C5：确认 `horizon_classifier.md` 的 SH5/SW2/SW3 改为 `unit: pct`、阈值 0，并保证 feature_catalog 单位逐项一致（工作区里目前是未提交改动，请提交）；② `horizon_classifier.md` 附录只留指向 feature_spec 的指针；③ feature_spec §10.2 按第 4 节的裁定处理 delisted/missing_from_list；④ V1–V12 和 ipo_allot 买入日的待核实项在 T-B05 实测时补上。
- **测试员**：① 更新 market_rules 快照，以及 alembic head 的已知列表（0016）；② T-T16 覆盖 candidate 快照必须带 user_id；③ 加用例：ETF 在 data_source 为 null 时一律 T+1。
- **前端**：显示 `planned` 状态；风险标记文案按契约 #29 改。
