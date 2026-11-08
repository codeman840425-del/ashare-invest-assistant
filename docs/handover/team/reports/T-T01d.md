# T-T01d 认证/会话/CSRF 测试 · 契约 v0.2.4 → v0.2.5 同步（测试）

- 角色：测试；工作树 `/workspace/wt-tests-T-T01`，分支 `test/T-T01`；**仅本地提交，未推送**（推送需用户批准）
- **HEAD：`62a1d66`**（其下 `b0a44e6`、`942c56c` 同属 T-T01d）；基于 origin/main `7107ead`
- **最新（11:4x 北京时间 / 20:4x MST）：推送就绪点更新为 HEAD `5c0fec5`**（在 `d018fad` 之上加评审 review-d018fad M1–M4、m1/m2、T-B30/T-B30a 验收用例、fmt_a quantity_match 键后缀），整链只改 tests/；**须与后端 `6670b10`、`9e693b2`、`d3be426` 等本地 main 提交一起推送**；详见文末“推送就绪点（更新 11:4x）”
- 11:1x：推送就绪点曾为 HEAD `d018fad`（在 `e5fb12c` 之上加 `b041cec`、`fb35b0f`、`8e3f36a`、`cd65fd6`、`d018fad`），整链只改 tests/；**`d018fad` 须与后端 `6670b10`（及其本地 main 前置）一起推送**；详见 reports/T-T25.md §8 与文末“推送就绪点（更新 11:1x）”
- 10:1x：推送就绪点曾为 HEAD `e5fb12c`（在 `a570315` 之上依次加 `3d7a789`、`7489eaf`、`1610531`、`d0ca02d`、`ab7c0de`、`f0df337`、`e5fb12c`），基于 origin/main `0cb78ad`，整链只改 tests/；origin 上 8 个失败须待本地 main 后端提交（T-B03c/T-B03e）先推；详见 reports/T-T25.md §7 与文末“推送就绪点（更新 10:1x）”；
- 08:4x：推送就绪点曾为 HEAD `a570315`（在 `b8d4d57` 之上加裁定提交 `c35c72c` 与 T-T25 提交 `a570315`），基于 origin/main `0cb78ad`，单独推送即全绿，详见文末“推送就绪点（更新 08:4x）”**
- 08:1x：推送就绪点曾为 HEAD `b8d4d57`（含 T-T22、T-T23、T-T24），基于 origin/main `0cb78ad`，单独推送即全绿（含覆盖率门槛 81.18%），详见文末“推送就绪点（更新 08:1x）”；更早的就绪点 `caa1f09` 已被取代**
- 只改了 `tests/`（另：`/tmp/tb02/db_selftest.py` 期望改为 0004，属工作树外的临时自检脚本，原件备份 `/tmp/db_selftest.py.pre-T-T01d`）
- 未调用麦蕊或任何真实行情 API；未读取 `.env` / 密钥；本报告不含任何原始敏感值

## 1. 指令沿革（steering）
| 时间 | 指令 | 状态 |
|---|---|---|
| 14:16 | T-T01d：注册/登录/登出/会话/CSRF/改密/`/me` 与负向安全用例；DB 自检期望 0004；对真实应用与 aia 栈跑；全套 + 秘密扫描 + 泄露扫描；本地提交 | 完成 |
| 14:26 | 补充 | 完成 |
| 05:34 | 契约 v0.2.4 §9 用例；§4.1 处理选项表跳过需写原因注释 | 完成（`942c56c`） |
| 05:38 | 同意书/风险测评用例暂停（on hold） | 已被 05:45 取代 |
| 05:42 | 修 T-O03 提到的 3 个 fixtures 问题；rebase 到 origin/main 7107ead；只用工作树 `deploy/scripts/up.sh`/`down.sh` 起停；按 T-O03 临时命令；带 M1 nginx 修复重跑 live 契约与认证；检查 PG 卷前后 | 完成（`b0a44e6`） |
| 05:45 | v0.2.5（bd33f83，T-A06）：(a) 删除同意/测评旧用例（不留 skip）；(b) 加 T-A06 五组用例，bd33f83 在 origin 则 rebase；(c) 未同步部分 xfail(strict=False)，reason 写责任人 | 完成（`62a1d66`） |

## 2. v0.2.5 同步（`62a1d66`）
### 2.1 删除（已提交与未提交的都删，未留 skip）
<redacted:sensitive-value-or-command>
- 注册用例改为 `test_register_open_creates_pending_user_and_no_session`（不再查同意种类）。
- CSRF 用例原以同意端点为载体，改用 `/auth/logout`、`/auth/password`：伪造 → logout 403；无 CSRF 改密无副作用（旧密码仍 200、新密码 401）；未登录 `/auth/password`、`/auth/logout` 401；轮换后旧 CSRF 登出 403、新 CSRF 登出 204。
- `/meta/registration` 断言字段集合恰为 `{"mode"}`。

### 2.2 新增（T-A06 五组）
| 组 | 用例 | 标记/责任人 |
|---|---|---|
<redacted:sensitive-value-or-command>
| 2 注册忽略 agreements、不写同意 | `test_v025_register_ignores_agreements_and_writes_no_consent[absent/legacy]`（表不存在视为 0 行） | xfail → 后端 T-B03b |
| 3 无同意/测评门槛 | `test_v025_me_has_no_consent_or_assessment_keys`（xfail → T-B03b）；`test_v025_no_403_gate_without_or_with_low_profile`（⚖ 端点 + POST /imports、/trades 不出 403；未标记，**已通过**） | |
| 4 周期分类器 1.2.0 hints | `test_v025_horizon_assessment_has_hints_and_classifier_1_2_0`（xfail → **后端 T-B30**）；单元 `unit/test_horizon_cases.py` 18 例（hint 模式、IT0 cap、case B/E、空画像等）全部通过；快照 `config_defaults/horizon_classifier.yaml` 换为 bd33f83 plan §6.1（version_no 3 / 1.2.0） | |
| 5 策略实例不适配 → 201 + warnings | `test_v025_strategy_instance_unsuitable_horizon_is_201_with_warnings` | xfail → **后端（策略实例 POST，尚无任务号）** |
| 枚举/错误码 | `test_meta_enums.py`：CONTRACT_VERSION v0.2.5；`test_v025_contract_drops_consent_and_assessment_items`（docs 仍 v0.2.4 时 xfail → 运维推送）；`test_v025_meta_enums_drops_consent_and_assessment_items`（xfail → **后端 T-B01 / T-B03b**）；解析计数 v0.2.5 为 56 枚举/22 码组 | |

- **前端 T-F02 的 v0.2.5 同步**：前端测试在 `src/frontend`，不在本人范围，未改。
- **rebase**：bd33f83 只在本地 main，origin/main 仍为 7107ead → 未 rebase（按指令"在 origin 上才 rebase"）。
- `docs/strategies/horizon_classifier.md` §7 case E 在 bd33f83 仍按 1.1.0 → 研究员（T-A06 §6）。

## 3. 05:42 指令执行记录
- **3 个 fixtures 问题**（T-O03）：原因是 origin/main 缺 T-T01 的夹具提交；分支上已补齐，`check_fixtures` 0 失败（origin docs 与 v0.2.5 docs 各一次）。
- **rebase** 到 7107ead：无冲突。
- **栈**：`env -u COMPOSE_PROJECT_NAME AIA_UP_BUILD=0 deploy/scripts/up.sh`（未重建镜像）；nginx 因 M1 修复被重建；栈期间被他人重启过一次，未影响结果。未动 ci-drill-*/tb03-*/be-b03a-*。
- **PG 卷**：前后均为 `aia_pgdata`，174 张表，无 `aia-t01_*` 新卷 → 数据卷保留。
- **意外**：up.sh 的 migrate 步骤把 **0004 应用到了主库**（T-O03 §10.1 原本跳过）→ 请运维确认是否接受/回退。
- live 认证用例路径修正为 `/auth/password`。

## 4. 结果（HEAD 62a1d66）
| 运行 | 结果 |
|---|---|
| 工作树（tests venv，无 argon2，含 live 栈 <url> | 376 passed, 246 skipped, 6 xfailed, **0 failed** |
| 其中 live 契约/认证/网关 | 21 passed |
| CI 模拟（7107ead 树 + argon2 + 临时 PG/Redis，全量 + 覆盖率） | 633 passed, 92 skipped, 34 xfailed, 0 xpassed, **0 failed**；行覆盖 90.4%（门槛 80%），check_coverage 通过 |
| CI 模拟 · v0.2.5 docs（bd33f83） | 464 passed, 83 skipped, 32 xfailed, 0 failed |
| CI 模拟 · v0.2.4 docs（35f4880） | 462 passed, 83 skipped, 34 xfailed, 0 failed |
| check_fixtures | 0 失败 |

xfail 共 34 条（全部 strict=False，reason 写责任人），清单见附录。

## 5. 扫描（HEAD 62a1d66）
- secret_scan：range `origin/main..HEAD` 122 个文件版本 阻断 0 警告 0；tree 406 个 阻断 0 警告 0
- gitleaks v8.30.1（`--redact --ignore-gitleaks-allow`）：`7107ead..HEAD` 15 commits no leaks；`--all` 63 commits no leaks
- 泄露扫描（team/samples 中 ≥6 位数字串，减去 fake_identifiers，对比新增行）：`b0a44e6..HEAD` 0 命中；`origin/main..HEAD` 5 个不同串命中，4 个为日期/整数/契约中已有值，1 个来自已登记的脱敏主夹具 positions_sample.txt（T-T01 早先提交）→ **0 个无法解释**。只记录计数，未输出原值。

## 6. 发现
- 契约 §7.1 "closed 一律 503" 与后端先做 schema 校验（畸形请求体 400）冲突 → 架构师裁定。
- 登录锁定计数的枚举口径（锁定期间失败是否计数）待架构师明确。
- 后端 CONTRACT_VERSION 与 `/meta/enums` 仍未同步 v0.2.3–v0.2.5。

## 7. 阻塞（按责任人）
- **运维**：把 bd33f83（以及 308afd3）推到 origin；确认 0004 已被应用到主库是否可接受。
- **后端**：T-B03b（删同意/测评端点、表、门槛，Me 去字段）；T-B01（enums/errors v0.2.5）；T-B30（分类器 1.2.0 + `/horizon-assessments`）；策略实例 POST（warnings，无任务号）；T-B03 跟进（apply_note、绝对 TTL、Cookie 双提交 CSRF、改密轮换会话）；T-B03a（限速/锁定/可信代理）；T-B03c（邀请码）；T-B02a（config/imports.yaml）；T-B16。
- **架构师**：closed 模式畸形请求体；锁定计数口径。
- **研究员**：`horizon_classifier.md` case E 与 caps kind（T-A06 §6 / T-A07 §4）。
- **前端**：T-F02 的 v0.2.5 同步（src/frontend 测试）。
- **用户**：批准推送 `test/T-T01`。

## 附录：xfail 清单（34）
- api_app/test_auth_t_b03.py::test_register_closed_rejects_even_malformed_body_with_503 | 契约 §7.1“closed 一律 503”；后端先做 schema 校验，畸形请求体返回 400（待架构师裁定）
- api_app/test_auth_t_b03.py::test_register_accepts_apply_note | T-B03 跟进（契约 v0.2.3 #25/#26，T-A05 7c62f59）：后端尚未实现（RegisterIn
- api_app/test_auth_t_b03.py::test_register_invalid_invite_codes_share_one_response_body | T-B03c（契约 #27 邀请码）：未实现前 invite 模式按 closed 返回 503
- api_app/test_auth_t_b03.py::test_cookie_max_age_is_absolute_ttl | T-B03 跟进（契约 v0.2.3 #25/#26，T-A05 7c62f59）：后端尚未实现（Cookie Max-
- api_app/test_auth_t_b03.py::test_session_past_absolute_ttl_is_401 | T-B03 跟进（契约 v0.2.3 #25/#26，T-A05 7c62f59）：后端尚未实现（无绝对过期：滑动续期可
- api_app/test_auth_t_b03.py::test_csrf_double_submit_requires_cookie_to_match[mismatch] | T-B03 跟进（契约 v0.2.4，T-A05 35f4880）：后端尚未实现（CSRF 只比对请求头与会话令牌，不看
- api_app/test_auth_t_b03.py::test_csrf_double_submit_requires_cookie_to_match[absent] | T-B03 跟进（契约 v0.2.4，T-A05 35f4880）：后端尚未实现（CSRF 只比对请求头与会话令牌，不看
- api_app/test_auth_t_b03.py::test_change_password_rotates_current_session | T-B03 跟进（契约 v0.2.3 #25/#26，T-A05 7c62f59）：后端尚未实现（改密保留当前 sid，
- api_app/test_auth_t_b03.py::test_bruteforce_5_failures_lock_15_minutes | T-B03a：限速/渐进锁定/可信代理尚未实现（T-B03 报告声明延后）
- api_app/test_auth_t_b03.py::test_login_rate_limited_per_ip | T-B03a：限速/渐进锁定/可信代理尚未实现（T-B03 报告声明延后）
- api_app/test_auth_t_b03.py::test_register_rate_limited_per_ip | T-B03a：限速/渐进锁定/可信代理尚未实现（T-B03 报告声明延后）
- api_app/test_auth_t_b03.py::test_client_supplied_x_real_ip_not_trusted | T-B03a：限速/渐进锁定/可信代理尚未实现（T-B03 报告声明延后）；nginx 也未设置/覆盖 X-Real-I
- api_app/test_auth_t_b03.py::test_v025_retired_consent_and_assessment_endpoints_are_404[POST /me/consents] | 后端 T-B03b（契约 v0.2.5 / T-A06 §3：删同意与测评端点、表、门槛，注册忽略 agreements，Me 删 consents/risk_assessment）
<redacted:sensitive-value-or-command>
<redacted:sensitive-value-or-command>
- api_app/test_auth_t_b03.py::test_v025_register_ignores_agreements_and_writes_no_consent[absent] | 后端 T-B03b（契约 v0.2.5 / T-A06 §3：删同意与测评端点、表、门槛，注册忽略 agreements
- api_app/test_auth_t_b03.py::test_v025_register_ignores_agreements_and_writes_no_consent[legacy] | 后端 T-B03b（契约 v0.2.5 / T-A06 §3：删同意与测评端点、表、门槛，注册忽略 agreements
- api_app/test_auth_t_b03.py::test_v025_me_has_no_consent_or_assessment_keys | 后端 T-B03b（契约 v0.2.5 / T-A06 §3：删同意与测评端点、表、门槛，注册忽略 agreements
- api_app/test_auth_t_b03.py::test_v025_horizon_assessment_has_hints_and_classifier_1_2_0 | 后端 T-B30（周期分类器 1.2.0 与 GET /horizon-assessments 尚未实现；T-A06 §
- api_app/test_auth_t_b03.py::test_v025_strategy_instance_unsuitable_horizon_is_201_with_warnings | 后端（策略实例 POST，契约 v0.2.5 / T-A06 §1.4、§3：删 fit_ack 校验、加 warnin
- api_app/test_config_yaml_defaults.py::test_backend_upload_limit_key_path | 后端 T-B02a 跟进（T-A05：新建 config/imports.yaml 与模型，键路径 imports.*，
- api_app/test_config_yaml_defaults.py::test_snapshot_equals_plan_block[horizon_classifier] | plan §6.1 仍为 v0.2.4：架构师 T-A06 bd33f83（v0.2.5，分类器 1.2.0）未推到 o
- api_app/test_config_yaml_defaults.py::test_backend_business_files_equal_plan_6_1 | 后端 BUSINESS_FILES 缺 auth、imports：后端 T-B03 跟进（T-A05：新建 config
- api_app/test_config_yaml_defaults.py::test_backend_model_accepts_plan_snapshot[horizon_classifier] | 后端模型拒绝 plan §6.1 快照的 horizon_classifier.yaml（['rules.horizon
- api_app/test_config_yaml_defaults.py::test_backend_model_accepts_plan_snapshot[imports] | 后端没有 imports.yaml 的模型：后端 T-B02a 跟进（T-A05：新建 config/imports.y
- api_app/test_config_yaml_defaults.py::test_backend_model_accepts_plan_snapshot[auth] | 后端没有 auth.yaml 的模型：后端 T-B03 跟进（T-A05：新建 config/auth.yaml 与模型
- api_app/test_config_yaml_defaults.py::test_repo_yaml_equals_plan_defaults[horizon_classifier] | 仓库 config/horizon_classifier.yaml 与 plan §6.1 快照不一致 ['classi
- api_app/test_config_yaml_defaults.py::test_repo_yaml_equals_plan_defaults[imports] | config/imports.yaml 未创建（plan §6.1）：后端 T-B02a 跟进（T-A05：新建 con
- api_app/test_config_yaml_defaults.py::test_repo_yaml_equals_plan_defaults[auth] | config/auth.yaml 未创建（plan §6.1）：后端 T-B03 跟进（T-A05：新建 config/
- api_app/test_meta_enums.py::test_contract_header_version | docs 仍为 v0.2.4：契约 v0.2.5（T-A06 bd33f83）未推到 origin（运维推送）
- api_app/test_meta_enums.py::test_v025_contract_drops_consent_and_assessment_items | docs 仍为 v0.2.4：契约 v0.2.5（T-A06 bd33f83）未推到 origin（运维推送）
- api_app/test_meta_enums.py::test_v025_meta_enums_drops_consent_and_assessment_items | 后端 T-B01 / T-B03b（契约 v0.2.5 / T-A06 §3：errors.py、schemas/enu
- api_app/test_meta_enums.py::test_enum_names_and_values_match_contract | 后端 /meta/enums 未同步契约（T-B01 v0.2 修订；v0.2.3 由后端按 T-A03 同步：vers
- api_app/test_meta_enums.py::test_version_and_import_codes | 后端（T-B01 / v0.2.3–v0.2.5 同步）：app/schemas/enums.py 的 CONTRACT

## 推送就绪点（更新 08:4x 北京时间：取代下文 08:1x 的 `b8d4d57`）
- **推送就绪点 = HEAD `a570315`**（分支 `test/T-T01`，基于 origin/main **`0cb78ad`**；`origin/main..a570315` 共 21 个提交，**全部只改 `tests/`**，已核对）。**未推送**，推送需用户批准。
  - 链：… → `b8d4d57`（T-T24）→ **`c35c72c`**（架构师裁定 2026-11-02，v0.2.9 687159f；取代未推送的 `3aaa153`）→ **`a570315`**（T-T25：契约 v0.2.9 验收 1–11 + 破坏性变更 #6/#11/#12 回归）。
- 结果（本地模拟 CI，临时 testcontainers PG/Redis）：

| 检查 | origin 0cb78ad + c35c72c | origin 0cb78ad + a570315 | 本地 main 687159f + a570315 |
|---|---|---|---|
| pytest | 800 passed, 93 skipped, 91 xfailed, 0 failed | **806 passed, 95 skipped, 119 xfailed, 0 failed** | **879 passed, 93 skipped, 42 xfailed, 6 xpassed, 0 failed** |
| 覆盖率门槛 80% | 81.18% 通过 | **81.18% 通过** | **83.54% 通过** |
| secret_scan range / tree | 143 / 497，阻断 0 警告 0 | 147 / 498，阻断 0 警告 0 | — |
| gitleaks range / --all | 20 / 153，no leaks | 21 / 153，no leaks | — |
| 泄露扫描 | 命中 11（同基线，0 新增） | 命中 11（同基线，0 新增） | — |
| check_fixtures.py | 0 失败 | 0 失败 | — |

- 注：`c35c72c` 在本地 main 687159f 上有 2 个 `test_meta_enums.py` 失败（docs 升 v0.2.9，该提交只认到 v0.2.8），已由 `a570315` 修正；因此 **`c35c72c` 与 `a570315` 须一起推送**（origin 上两者单独都全绿）。
- 6 个 xpassed：裁定 1（closed 模式畸形体 503），本地 main f72b8c7 已实现、origin 未有，保留 xfail(strict=False)。
- 详见 `T-T25.md`。

## 推送就绪点（更新 08:1x 北京时间：取代下文 07:2x 的 `caa1f09`）
- **推送就绪点 = HEAD `b8d4d57`**（分支 `test/T-T01`，基于 origin/main **`0cb78ad`**；`origin/main..b8d4d57` 共 19 个提交，**全部只改 `tests/`**，已核对）。**未推送**，推送需用户批准。
  - 链：`44cf748`（T-T01d）→ `caa1f09`（T-T22）→ `be700e0`（T-T23，契约 v0.2.8 §9）→ `b8d4d57`（T-T24：0008→0011 迁移升级、评审 116cb7e 补测、删除用户数据 CLI、KNOWN_HEADS 0011–0013）。
  - 须整链一起推（44cf748 单独覆盖率 72.5% 不过门槛）；到 b8d4d57 在 0cb78ad 上单独全绿。
- 结果（本地模拟 CI，临时 testcontainers PG/Redis）：

| 检查 | origin 0cb78ad + b8d4d57 | 本地 main（后端 8fd9502 / 前端 b34260f）+ b8d4d57 |
|---|---|---|
| pytest tests/backend tests/replay | **793 passed, 93 skipped, 73 xfailed, 0 xpassed, 0 failed** | **849 passed, 93 skipped, 17 xfailed, 0 xpassed, 0 failed** |
| 覆盖率门槛 80% | **81.18% 通过** | **83.42% 通过**（be700e0 时 76.65% 不过：`app/cli/delete_user_data.py` 0/369；T-T24 CLI 用例后 84%） |
| check_coverage.py | 通过 | 通过 |
| check_fixtures.py | 0 失败 | — |
| secret_scan range / tree | 141 / 496 个文件版本，阻断 0，警告 0 | — |
| gitleaks range / --all | 19 / 145 commits，no leaks | — |
| 泄露扫描 | 命中 11（与 be700e0 基线相同，均已解释，0 个新引入） | — |

- 详见 `T-T23.md`（含 T-T24 与 be-b03a-pg 核查）。

## 推送就绪点（更新：2026-11-02 07:2x 北京时间；取代 06:3x 的 `88858e5` 及之后的 `6f07be1`/`b2642ab`、`40d83ba`/`7a738b9`）
- **推送就绪点 = HEAD `caa1f09`**（分支 `test/T-T01`，基于 origin/main **`0cb78ad`**（T-O10），`origin/main..caa1f09` 共 17 个提交，**全部只改 `tests/`**，已逐提交核对）。**未推送**，推送需用户批准。
  - 其中 **T-T01d 提交 = `44cf748`**，**T-T22 提交 = `caa1f09`**（父为 44cf748）。
  - **两者必须一起推送**：`44cf748` 单独在 0cb78ad 上 0 failed，但整体行覆盖 72.5% < 80%（T-B45 证书代码只被 T-T22 用例覆盖），CI 覆盖门槛会失败；到 `caa1f09` 为 81.18%。
- 被取代的旧哈希（均未推送，可忽略）：`88858e5`/`aca3c34`（onto b79ce80）、`6f07be1`/`b2642ab`（onto 713a276）、`40d83ba`/`7a738b9`。备份分支（仅本地）：`backup/T-T01-pre-713a276`、`backup/T-T01-pre-v027`、`backup/T-T01-pre-0cb78ad`。

### 本轮改动（并入 44cf748）
- **fixtures**：origin 上 `check_fixtures` 的 3 个问题（meta.json 缺 `fake_identifiers`、缺 `expected.json`、3.5A-2 ③ §4.1 46 码未覆盖）由本分支 T-T01 系列提交补齐；在 0cb78ad 上复跑 0 失败。
- **变基**：onto origin/main `0cb78ad`（无 tests/ 冲突；0cb78ad 已含 T-B03c 迁移 0008、契约 v0.2.7 docs fa6d55d/35517f8）。
- **契约 v0.2.7 常量（编排 06:42，未放松断言）**——原先失败的 3 个用例与对应常量：
  1. `test_meta_enums.py::test_contract_header_version` → `CONTRACT_VERSION = "v0.2.7"`
  2. `test_meta_enums.py::test_contract_parsers_sanity` → 码表计数 `CODE_COUNTS["v0.2.7"] = (59, 22)`、`V027_ENUMS`（18 个新枚举）、`data_provider` 加 `exchange`；修 `parse_enums` 误收说明文字里反引号片段
  3. `test_config_yaml_defaults.py::test_plan_6_1_lists_eight_files` → 改为 `test_plan_6_1_lists_nine_files`，`NAMES` 加 `securities`（九个文件，新增 `config_defaults/securities.yaml` 快照）
- **m11 #3**：alembic head 断言 `KNOWN_HEADS = ("0008",)`（0007 已被 0008 T-B03c 取代）；`Me` 必含 `data_licence_status`（新用户 `not_set`）。
- **invite 模式已实现（T-B03c）**：原 `[closed, invite]` 参数化拆为 `test_register_when_closed_is_503_and_writes_nothing` 与新增 `test_register_invite_mode_without_code_is_400_and_writes_nothing`（400 VALIDATION_ERROR，fields 含 invite_code invalid / apply_note required，不建用户）；去掉 `test_register_invalid_invite_codes_share_one_response_body` 的 strict xfail。
- **新增 `tests/backend/unit/test_import_resolutions_t_b02x.py`**：origin 上 `app/importing`（T-B02x f739296）行覆盖 0% < 90%，`check_coverage` 失败；补契约 §4.1 处理选项表的单元测试后 97.9%。

### 结果（本地模拟 CI：origin/main 0cb78ad 树 + 后端 venv + 临时 PG/Redis）
| 检查 | 44cf748（T-T01d） | caa1f09（HEAD，推送就绪点） |
|---|---|---|
| backend job：pytest tests/backend tests/replay | 717 passed，**0 failed** | **787 passed, 93 skipped, 17 xfailed, 0 xpassed, 0 failed**（10 subtests passed） |
| 覆盖率门槛（--cov-fail-under=80） | **72.5%，不过**（须与 caa1f09 一起推） | **81.18%，通过** |
| check_coverage.py 领域包 ≥90% | — | importing 97.9%；domain/signals/advice/llm 无语句；**通过** |
| fixtures job / secret-scan 夹具一致性（`check_fixtures.py`，pyyaml 6.0.3） | 0 失败 | **0 失败**（1 个夹具目录，§4.1 46 码全覆盖） |
| secret_scan.py range `origin/main..` | 129 个文件版本，阻断 0，警告 0 | 133 个，阻断 0，警告 0 |
| secret_scan.py tree | 488 个，阻断 0，警告 0 | 492 个，阻断 0，警告 0 |
| gitleaks（`--redact --ignore-gitleaks-allow`） | range 16 commits no leaks；`--all` 131 commits no leaks | range 17 commits no leaks；`--all` no leaks |
| 泄露扫描（team/samples 数字串对比新增行） | 0 个新引入 | 0 个新引入（唯一既有命中来自已登记脱敏主夹具；只记计数，不输出原值） |
<redacted:sensitive-value-or-command>

### live 复跑（编排 07:01 (A)；aia-t01 由运维重建，api/ingest 创建于 06:55 北京时间，均 healthy）
- 未对 aia-t01 运行 up.sh/down.sh；未触碰 `/workspace/aia-t01-deploy`（0cb78ad 干净检出）。
- `test_gateway_live.py` + `test_contract_live.py` + `test_auth_live.py`（`AIA_CONTRACT_BASE_URL=<url>`）：**18 passed，8 subtests passed，0 failed**。
- 核对：没有 live 用例期望 nginx 返回 429（dev 下 nginx 限速只记日志）；没有用例期望 api 读密文列。
- **DB 自检（只读）**：`alembic_version = 0008`（断言由 0007 改为 0008）；`has_column_privilege('aia_api', 密文列/licence_hmac, SELECT) = false`，对 `user_data_licence_status` 视图 SELECT = true。自动化断言见 T-T22 的 `test_api_role_cannot_select_ciphertext`（测试库未施加角色时 skip）。

### 阻塞（按责任人，T-T01d 范围）
- **用户**：批准推送 `test/T-T01`（须 44cf748 + caa1f09 一起）。
- **运维**：CI 测试库未施加 aia_api/aia_ingest 角色（相应用例 skip）；契约 v0.2.8（6ef79c4）及之后的本地 main 提交尚未在 origin。
- **后端 T-B01**：后端 `/meta/enums` 未报 v0.2.7（相关用例为非严格 xfail）；`config/securities.yaml` 尚未提交。
- **架构师**：closed 模式畸形请求体 503 vs 400、锁定计数口径（旧遗留，见 §6）。


## 推送就绪点（更新 10:1x）

- HEAD **`e5fb12c`**（分支 `test/T-T01`），基于 origin/main `0cb78ad`；`origin/main..e5fb12c` 共 28 个提交，非 tests/ 路径 0。
- 全量：origin 825 passed / 113 skipped / 246 xfailed / **8 failed**（R1 closed 模式 ×6、CSRF ×2：严格断言本地 main 后端行为，origin 未有 → 后端提交须先推），覆盖率 81.27% ✅；本地 main be8d13a 1000 passed / 111 skipped / 80 xfailed / 1 xpassed / 0 failed，覆盖率 73.51% ❌（后端 T-B46：整体 / domain / importing 低于门槛）。
- 扫描：secret_scan 阻断 0 警告 0；gitleaks no leaks；泄露扫描 19（0 新增披露，说明见 T-T25.md §7.3）；check_fixtures 0 失败。
- **未推送**，等待用户确认。

## 推送就绪点（更新 11:1x 北京时间：取代上文 10:1x 的 `e5fb12c`）

- HEAD **`d018fad`**（分支 `test/T-T01`），基于 origin/main `0cb78ad`；`origin/main..d018fad` 共 33 个提交，非 tests/ 路径 0。
- 全量：本地 main `2d46332`（含 6670b10）**0 failed** / 1131 passed / 115 skipped / 61 xfailed / 7 xpassed，覆盖率 73.34% ❌（后端 T-B46）；origin 0cb78ad **9 failed**（既有 8 + 1 个须 6670b10）/ 853 passed / 117 skipped / 335 xfailed，覆盖率 81.27% ✅。
- 推送顺序：后端 `6670b10` 及前置（`origin/main..6670b10` 69 个提交；G-7 用例另需 `ab84776`，测试基线 2d46332）须与本分支一起推。本地 main 已到 `6efedef`，未在其上运行。
- 扫描：secret_scan 阻断 0 警告 0；gitleaks range no leaks，`--all` 4 处在后端 3e5e288（b3aab3c 已修，owner 后端）；泄露扫描 19（0 新增披露）；check_fixtures 0 失败。
- **未推送**，等待用户确认。

## 推送就绪点（更新 11:4x 北京时间 / 20:4x MST：取代上文 11:1x 的 `d018fad`）

- HEAD **`5c0fec5`**（分支 `test/T-T01`），基于 origin/main `0cb78ad`；`origin/main..5c0fec5` 共 34 个提交，非 tests/ 路径 0；`d018fad..5c0fec5` 10 个文件 +357/−24。
- 内容（按 reports/review-d018fad.md）：
  - M1：`KNOWN_HEADS` 加 0018、0019；`test_alembic_head_is_known` 改为解析 migrations/versions 唯一树头，断言库版本 = 树头且在 KNOWN_HEADS 中（其他 head 断言已排查：t24 `_require_0013` 用 `<` 比较，无需改）。
  - M2：错误码条数改为从契约 §4 表行解析（`contract_error_row_count`），不再硬编码 59/60；新增 T-B50 断言：/meta/enums 含 `plan_status`、`plan_condition_type`、证券对账枚举，error_codes 含 414 `URI_TOO_LONG`（本地 main 严格通过；origin docs/后端未同步处条件 xfail，写责任人）。
  - M3：R6 `_trade` 以字符串发送 qty / price（R11 #9）。
  - M4：`config_defaults/securities.yaml` 同步 plan §6.1 新增 `master` 段（原文照抄）；origin 上按 T-A04 docs 未推 / 后端 T-B51 条件 xfail。
  - m1：ETF 无 data_source 恒 T+1 改为逐参数 12 例（null ×6、"" ×6）严格断言——本地 main 12 例全部通过（9e693b2 已修 "" 门控），故 "" 参数不再挂 xfail；origin 上 `_lots()` 运行时 xfail（O_LOTS）。r8 pattern 去 xfail。
  - m2：`test_v025_horizon_assessment_has_hints_and_classifier_1_2_0` 去 xfail，归 T-B47（c9e1e73）；origin 无 /horizon-assessments 路由时运行时条件 xfail（不让 origin 变红）。
  - 新增 `test_horizon_t_b30a_acceptance.py`（20 例 xfail strict=True，负责人 后端 T-B30a）：15 个 f.* 入 feature_catalog；GET 结果落库且 snapshot_id 为 data_snapshots 真实行（purpose=horizon、user_id=本人）；import / watchlist_add / weekly 三种触发各写一条评估；生成 status=proposed、origin=classifier 的 strategy_instances。另 1 例严格自检：horizon_classifier.yaml features 恰为这 15 个键。已用 `--runxfail` 在本地 main 上确认 20 例都在“功能缺失”的断言处失败（导入流程上传→previewed→confirm 全通，只在“无 trigger=import 评估”处失败），不是夹具问题。
  - fmt_a：expected.json quantity_match 键改为带 .SH/.SZ 后缀；`generate.py --check` 0 差异；主夹具 sha256 不变。

| 检查 | 本地 main `fdd7fdd` + 5c0fec5 | origin `0cb78ad` + 5c0fec5 |
|---|---|---|
| pytest 全量 | **0 failed** / 1157 passed / 115 skipped / 74 xfailed / **0 xpassed** | **9 failed**（与 d018fad 相同的既有 9 个，0 新增）/ 854 passed / 117 skipped / 366 xfailed / 0 xpassed |
| 覆盖率 | 总 80.57% ✅；check_coverage ❌：app/domain 65.7%、app/importing 71.8% < 90%（后端 T-B46 / T-B46-x） | 总 81.27% ✅；check_coverage ✅ |

- origin 9 个失败（均为测试先行、须后端提交先推）：R1 closed 模式畸形体 503 ×6、CSRF 双提交 ×2（T-B03c/T-B03e/T-B47）、`test_t16_db_rejects_candidate_snapshot_without_user`（须 6670b10 迁移 0017）。
- 推送清单：本地 main `origin/main..fdd7fdd` 共 115 个提交，**已验证基线是整段**（0 failed）。最低要求（未单独跑）：至少到 `d3be426`（第 82 个，含 6670b10 / ab84776 / 9e693b2）；若推到 `3e5e288`（第 86 个）或之后，须一并推 `b3aab3c` 与 `2954b6c`（gitleaks 豁免），否则 gitleaks `--all` 有 4 处命中（owner 后端）。
- 评审 §4：origin 与本地 main 的 `.github/workflows/ci.yml` 都不设 `AIA_CONTRACT_BASE_URL`，test_contract_live 在 CI 中按“服务不可达 skip”处理，无需改动。
- 扫描：secret_scan range 209 / tree 507 文件版本，阻断 0 警告 0；gitleaks range 34 commits no leaks，`--all` 4 处仍在后端 3e5e288（本地 main 2954b6c 已豁免，未推）；泄露扫描 19 命中，与 d018fad 完全相同（0 新增披露）；check_fixtures 0 失败；非 tests/ 路径 0；fmt_a sha256 不变。
- **未推送**，等待用户确认。
