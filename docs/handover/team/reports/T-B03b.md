# T-B03b 报告（缩减版）—— 后端

- 提交：**48b6686**（仅本地提交，未 push；`git commit --only -- <精确路径>`，11 个文件）
- 范围按编排者 5:38 STOP-CHANGE 缩减：风险测评（docs/strategies/compliance 问卷）与同意相关部分（M2、M3、agreements 改 signal_risk_disclosure）**暂停，待 T-A06 / 契约 v0.2.5 给出删减清单**。现有同意/测评代码保持 HEAD 原样，未改也未删。
- 规则：未调用麦蕊（所有运行均 `env -u MAIRUI_LICENCE`，测试套件在 `unshare -rn` 断网下跑）；STOP 保留（sha256 02339d1e…7fbe17 不变）；只写 src/backend/ 与 config/；未碰 tests/、src/frontend/、deploy/、.github/、docs/、scripts/、probes/；config/strategies/ 未手写。

## 已完成
| 项 | 内容 | 文件 |
|---|---|---|
| imports.* | 新建 `config/imports.yaml`（键与默认值逐字取 plan §6.1）；`ImportsConfig`（extra=forbid，`max_request_bytes > max_file_bytes × max_files_per_upload`、扩展名小写带点且不重复）；`ingest.imports.*` → `imports.*`，`ingest.yaml` 注释块删除；旧键 `ingest.imports` 现被拒 | config/imports.yaml, config/ingest.yaml, app/config_files.py, app/main.py, app/common/errors.py |
| auth.yaml | 新建 `config/auth.yaml`：password / password_hash / session / invite / admin（`same_ip_highlight_threshold: 3`），**无 consents 段**（v0.2.4）；BusinessConfig 8 个文件，缺/多均启动失败 | config/auth.yaml, app/config_files.py, app/config.py |
| 敏感键扫描 | `auth.yaml` 的 `password` / `password_hash` 段键名命中敏感词扫描；加精确豁免：只限 auth.yaml 这两段，且所有叶子必须是整数/布尔，出现字符串仍拒 | app/config.py |
| 口令策略 | 长度、argon2 参数取 auth.yaml（`PasswordPolicy` / `policy_for`，依赖 `PasswordsDep`）；参数变更后登录透明升级哈希 | app/auth/passwords.py, app/auth/deps.py, app/api/v1/auth.py |
| M4 | 会话续期 TTL = min(idle, 绝对期限剩余)，过绝对期限即作废；Cookie Max-Age = `absolute_ttl_s` | app/auth/sessions.py, app/api/v1/auth.py |
| S3 | 改密吊销该用户**全部**会话（含当前），新建会话并下发新 sid / csrf_token，204 | app/api/v1/auth.py |
| S6 | `SESSION_COOKIE_SECURE=false` 只允许 APP_ENV=local/test，否则启动失败 | app/config.py |
| 注册字段 | 契约 v0.2.4 #2：display_name 1–32、新增 `apply_note ≤200`（去空白，空串存 NULL）；与同意/测评无关，保留 | app/api/v1/auth.py |

## 暂停（paused pending T-A06）
- M2：同意版本须等于当前文书版本（原方案 `legal.current_versions`）。
- M3：`require_consent(key)` 依赖工厂（403 CONSENT_REQUIRED）。
- agreements 键改为 `signal_risk_disclosure`、可选 `sensitive_financial_info`；ConsentIn 4 个 key。
- 风险测评改按研究员问卷规格计分（evaluate、K4、24h 限 3 次、有效期）。
- `/meta/registration` 现状不变（HEAD 已是 `{mode}`）。
- 以上未提交的实现已备份到 `/tmp/park/T-B03b-full/`（tracked.patch + legal.py + questionnaires/），工作树已还原为 HEAD 版本，便于 T-A06 后按清单取舍。
- T-B16：**未开始**，无任何迁移或半成品。

## 验证
- ruff check / ruff format / mypy --strict（50 个文件）全部通过。
- 自检（隔离容器 be-b03a-pg / be-b03a-redis）：`/tmp/tb02/selftest_tb03b.py` 121/121（含原 T-B03 用例 + M4、S3、S6、敏感键豁免、apply_note）；`selftest_api.py` 201/201（含 imports.yaml、8 文件白名单、缺 imports.yaml 启动失败、旧键被拒；对照 v0.2.3 契约快照，因为 enums 升 v0.2.4 本来属于 T-B16，现已暂停）。
- 测试方工作树 wt-tests-T-T01（85214f7，只读，`-p no:cacheprovider`、`PYTHONDONTWRITEBYTECODE=1`、`AIA_CONFIG_DIR=<仓库>/config`）：api_app + unit **494 passed / 226 skipped / 5 xfailed / 0 failed**。`test_repo_yaml_equals_plan_defaults[imports|auth]` 由 xfail 转为通过。剩余 xfail 是测试侧 plan/契约快照未同步，以及 CONTRACT_VERSION v0.2.4，后者待 T-A06 定。
- 密钥扫描：提交文件无证书或口令字面量，licence 命中 0；STOP sha 不变。

## 备注 / 需要他人
- 测试：不设 `AIA_CONFIG_DIR` 时，`test_repo_yaml_loads_in_settings` 读的是工作树自己的 config/（没有 imports.yaml），所以会失败。请同步 plan §6.1 快照（imports / auth），并让该用例默认指向仓库 config。
- 测试/后端：`Settings(config_dir=...)` 这个初始化参数不影响业务 yaml 的加载（加载目录只取 `CONFIG_DIR` 环境变量），这是既有行为；我的自检已改用环境变量。是否需要统一，后续再定。
- 架构：invite 模式 V1 是否推迟（plan 3.3 / review-T-F02 #11 与 T-B03c 冲突），在 T-B03c 里一并说明。
- 遗留：S5（清理 user_sessions 集合）未做。

## 跟进（T-O03 四项，2026-11-02）
1. **imports.yaml**：已包含在 48b6686 中。
2. **在本地开发库执行 0004**
   - 共享库 aia-t01-postgres-1 在我介入前就已经是 0004；前后两次 `alembic current` 都是 0004，我没有执行迁移。
   - aia-main 栈没有启动。
3. **X-Forwarded-For**：提交 a250379。
   - 只信任最右一跳（我方 nginx 追加的那一跳），并新增 TRUSTED_PROXIES。
   - `selftest_xff` 21/21，覆盖伪造的多跳头。
   - 这部分已从 T-B03a 移出，T-B03a 不再重复实现。
4. **/meta/enums**：21cf382 曾升到 v0.2.4 并加了 4 个枚举。由于 v0.2.5（bd33f83）已发布，T-B16（4162abb）又升到 v0.2.5，同时删掉这 4 个枚举。304 保留。
