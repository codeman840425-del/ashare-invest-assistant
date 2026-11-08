# T-A21 草稿：里程碑批量评审 origin/main..dcf734d（只读助手）

- 范围：102 个提交，282 文件，+67314/−357。依据 dcf734d 的 docs/api-contract.md 与 docs/plan.md；`check_contract.py` 通过。
- 重点读的提交：c6ce767 T-B83、5a960e2 T-B83b、535f9fc T-B81、fa4ddea/ddb3991 T-B80、e31ed6c T-B84、9a9fc4f T-B78、ce32484 T-B77、b8f3f99/918f747/cc13f72/b9645bc/dcf734d T-F28–F31。其余提交（T-B5x/T-O*/T-B70–76 等）没有逐行读。
- 没有跑后端 selfchecks 和前端测试（需要库，而且会在仓库写缓存）。结论只来自读 diff 和全工作树扫描。

## 已核对、没发现问题（证据）
- 会话 origin：只有 auth.py:432（/auth/login）和 :514（/auth/password）用 `origin="password_login"` 建会话；sessions.py 读 Redis 时只认这个字面值，其他值和旧会话一律算 None。
- G7 和 lifecycle：都走 HumanDep（带 Authorization 头 → 403，origin 不对 → 403 加审计），再进 reauth.transaction。transaction 锁用户行，再查一次会话 origin 和 user_id；ACCOUNT_LOCKED；密码错 → 只提交失败计数和审计，然后返回 401 REAUTH_FAILED，计入锁定。CSRF 走 current_admin 的双提交校验。
- 密码不落地：两个请求体的 password 都是 `SecretStr(repr=False, exclude=True)`；audit、record_attempt 都不带密码；校验错误的 details 只有 field/issue，不回显 input。
- 状态机：draft→simulating 要求 review_id 已 approved、非 stale、版本和 content_sha256 一致、human_review.origin=password_login、G1–G7 没有 fail/skipped、warn 都已确认；stale → 409 PROMOTION_STALE{current_version_id}，未确认的 warn → 422 PROMOTION_WARN_UNACKNOWLEDGED。simulating→published 一律 422（MVP 没有 verified_live 证据链）。legacy_unbound 返回 200，只读。
- G6：max_jaccard 为 null 时 G6 只到 warn（g6.py:42；fixtures 没过才 fail，和 plan 2.5.13 一致）。G2：verified_doc 只放行到 simulating，declared 键阻断（source_reviews.py:209–217；DOC_KEYS 含 f.amount，f.market_regime_idx 单列，和 T-R19 一致）。
- 前端：密码用非受控 ref 读，读完即清空，不进 mutation variables 或缓存，`retry:false`；两个密码框都是 `type=password autoComplete="off"`（b9645bc）。REAUTH_FAILED 不触发全局跳登录；STALE、HUMAN_SESSION 有专门提示。新增调用都在契约内：/admin/promotions、…/decision、…/lifecycle、/promotion-requests/{id}。
- T-B81 证书：从固定临时文件读，读之前用 lstat 校验是普通文件、0600、属主是本人；不从环境变量回退；finally 里 unlink，并在 summary 里写 `temporary_secret_deleted`。异常一律换成固定原因（`from None`），关掉 logging，`allow_redirects=False`，响应里回显证书就不落盘。results/ 已 gitignore。/workspace/team/runtime 是 0700，目前没有 mairui 临时文件。测试只用合成值。

## 问题表
| 严重度 | 文件:行 | 提交 | 问题 | 归属 |
|---|---|---|---|---|
| P2 | src/backend/app/api/v1/promotions.py:57 | c6ce767 | 带 Authorization 头时先返回 403 HUMAN_SESSION_REQUIRED，后做管理员判定，未登录或非管理员也能看出 /admin 路由存在，和 §1.3“/admin/* 非管理员一律 404”冲突；应先 current_admin 再判断 token | 后端 |
| P2 | src/backend/app/api/v1/promotions.py:53,211 | 5a960e2 | 所有 lifecycle 转换都要求密码（契约只要求 draft→simulating 带）；`password` 为 null 时按密码错误计入锁定。要么契约写明全部转换都要重输密码，要么缺失时返回 400 且不计数 | 后端+架构师 |
| P2 | src/backend/app/strategy/promotions.py:216 | fa4ddea | 有 feature_requests 时 `quota_delta_per_min=None`，契约 §7 写的是 int，前端类型也是 number。现有两张卡都是 []，暂时触发不到；契约需改成 int\|null 加原因，或后端算出真值 | 架构师+后端 |
| P2 | src/backend/app/api/v1/promotions.py:156–164 | c6ce767 | /admin/promotions 先全表扫描，每行再做 review_context+summary（N+1），card_id/stale 在 Python 里过滤；分页结果没错，但数据量上来会变慢 | 后端 |
| P2 | src/frontend/src/pages/admin/AdminStrategyGatesPage.tsx:175,183 | b9645bc | 符合契约，但 Chromium 系浏览器对 password 框常常不理会 autocomplete=off。建议改成 `autocomplete="new-password"`，不放 form/name，并在契约里同步 | 前端+架构师 |
| P2 | src/backend/probes/tb81.py:27,242–249 | 535f9fc | 临时证书路径写死；进程被 SIGKILL 时 finally 不执行，文件会留下。运维 runbook 需加“运行前后确认文件不存在”和 umask/0700 目录要求 | 运维 |

P0：0；P1：0。

## 密钥扫描分类（`secret_scan.py tree`）
- 用仓库现有允许清单：807 个文件，阻断 0，警告 0。
- 无豁免（空 allow 和空 ignore）：阻断 80，警告 0。80 处逐条比对过（不输出值），全部是允许清单里已登记的 4 个虚构字面量（<account>、<account>、0000000001、0000000000，仅示意），没有其他值。

| 类别 | 命中 | 路径模式 | 结论 | 理由 | 归属 |
|---|---|---|---|---|---|
| 夹具 S5/S6（fmt_a） | 73（trades_sample 66、README 4、expected.json 2、positions_sample 1） | tests/fixtures/broker_statements/fmt_a/* | 白名单（已有） | 值都是登记过的虚构字面量，而且在 meta.json fake_identifiers 里；两个主样本已按 path+sha256+reviewer 登记 | 测试 |
| 扫描配置自引用 | 6 | .gitleaks.toml:150–151、.secretscan-allow.yaml:15/20/25/30 | 白名单（已有） | 允许清单本身就要写出这些虚构值 | 运维 |
| docs 示例 | 1 | docs/plan.md:1973 S5 | 白名单（已有） | 契约/plan 示例用的虚构值 | 架构师 |
| gitleaks generic-api-key | 1（T-F28 tree 报告，File 字段为空，第 30360 行，Match 以“feat”开头，熵 3.85） | 推断是 `feature_key: f.xxx` 这类 YAML/文档行 | 白名单（待定位后按指纹登记） | 特征键路径，不是密钥。本机没有 gitleaks，没能复现到具体文件，需运维用 gitleaks_run.sh 复跑后定位 | 运维 |
| 前端禁用词 | 2 | src/frontend/src/test/wording.test.ts:2,12 | 白名单（只对禁用词检查） | 这是禁用词校验的测试，必须列出这些词 | 前端/测试 |
| 前端连续 11 位以上数字 | 1 | src/frontend/src/mocks/marketFixtures.ts:64（turnover_total 字面量） | 白名单（按 path+值） | 成交额假数据，不是账号；也可以改成带小数的金额来消除命中 | 前端 |
| 其他数字/禁用词存量 | 276/9 | uv.lock、selfchecks、probes、docs | 不在本轮范围，不阻断 | 不是 secret_scan 的 S 规则，是执行器自加的检查 | 测试 |

结论：没有需要清理的真实值或高熵非占位值。

## 白名单规则草案（供写入 docs）
1. 只用 `.secretscan-allow.yaml` 的 `value_regex: '^字面量$'`（脚本已强制），一项只对应一条规则和一个虚构值；禁止通配、禁止整目录或 `rule: '*'` 豁免。
2. 按路径豁免必须同时写 `path`（精确文件）、`rule`、`sha256`、`reviewer`、`reason`、`added_by`、`added_at`；文件内容一改就失效，需要重新核验。
3. gitleaks 误报用 `.gitleaksignore` 指纹（`完整sha:文件:规则ID:行号`），不改规则、不加 `[allowlist] paths`。
4. 前端禁用词和数字检查：只豁免 `src/frontend/src/test/wording.test.ts`（仅禁用词）；假数据里的数字改成不会命中的形式，或者按“路径+规则+字面量”登记。
5. 新加白名单要由架构师或测试负责人评审（CODEOWNERS）；每次登记前，在本机用 check_real_secrets.sh 和真实值精确比对，结果为 0 才能登记，且不输出取值。

## 结论
- 推送点：**pass（有条件）**。P0/P1 都是 0；仓库允许清单下扫描 0/0；无豁免时的 80 处全是已登记虚构值。
- 条件：① CI 或本机跑一遍 selfchecks 和前端测试（本次没跑）；② 运维用 gitleaks 复跑，定位那 1 处 generic-api-key 并按指纹登记；③ 推送仍需用户本人批准。
- P2 项可以排到下一里程碑。
