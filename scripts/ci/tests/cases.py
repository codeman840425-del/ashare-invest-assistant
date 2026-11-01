"""S1–S9 正反例生成器（plan §7.4A 测试要求：每条规则至少一个命中用例和一个不误报用例）。

所有值都是运行时拼出来的虚构值，不是任何真实凭据或真实证件号。
"""

from __future__ import annotations

from dataclasses import dataclass

import secret_scan as ss

HOLDER = ss.HOLDER
W = ss.HEADER_WORDS
ACCOUNT = "\u8d44\u91d1\u8d26\u53f7"  # 资金账号
FULLWIDTH_COLON = "\uff1a"


def fake_token(n: int, alphabet: str = "TESTONLY") -> str:
    return (alphabet * (n // len(alphabet) + 1))[:n]


def fake_id(valid: bool) -> str:
    body = "110101" + "1990" + "0307" + "123"
    total = sum(int(c) * w for c, w in zip(body, ss._ID_WEIGHTS, strict=True))
    check = ss._ID_CHECK[total % 11]
    if not valid:
        check = "0" if check != "0" else "1"
    return body + check


def fake_card() -> str:
    body = "6" + "2" * 14
    for d in "0123456789":
        if ss.luhn_ok(body + d):
            return body + d
    raise AssertionError


@dataclass(frozen=True)
class Case:
    name: str
    path: str
    content: str
    py_block: set[str]  # secret_scan.py 期望的阻断规则
    py_warn: set[str]  # secret_scan.py 期望的警告规则
    gl_rules: set[str] | None  # gitleaks 期望命中的 S 规则（None = 不比对 gitleaks）


def cases() -> list[Case]:
    lic = fake_token(20)
    c: list[Case] = [
        # S1
        Case("s1-url", "src/a.py", "u = 'https://" + "mairuiapi" + ".com/hslt/list/" + lic + "'\n", {"S1"}, set(), {"S1"}),
        Case("s1-assign", "src/b.py", "MAIRUI_" + "LICENCE = '" + lic + "'\n", {"S1"}, set(), {"S1"}),
        Case("s1-neg-env", "src/c.py", "MAIRUI_LICENCE = os.environ['MAIRUI_LICENCE']\n", set(), set(), set()),
        Case("s1-neg-placeholder", "src/d.py", "u = 'https://" + "mairuiapi" + ".com/hslt/list/<licence>'\n", set(), set(), set()),
        # S2
        Case("s2-sk", "src/e.py", "k = '" + "s" + "k-" + fake_token(24) + "'\n", {"S2"}, set(), {"S2"}),
        Case("s2-sk-neg-short", "src/f.py", "k = 's" + "k-short'\n", set(), set(), set()),
        Case("s2-sk-neg-wordprefix", "src/g.py", "name = 'ta" + "sk-" + fake_token(24, "abc") + "'\n", set(), set(), set()),
        Case("s2-assign", "src/h.py", "api_key = " + '"' + fake_token(16, "T3st") + '"' + "\n", {"S2"}, set(), {"S2"}),
        Case("s2-assign-neg", "src/i.py", 'api_key = os.getenv("DEEPSEEK_API_KEY")\n', set(), set(), set()),
        # S3
        Case("s3", "keys/k.txt", "-----BEGIN " + "RSA PRIVATE" + " KEY-----\n", {"S3"}, set(), {"S3"}),
        Case("s3-neg", "keys/p.txt", "-----BEGIN PUBLIC KEY-----\n", set(), set(), set()),
        # S3：证书封装私钥（T-O09）。值在运行时拼出：前缀 + 虚构填充，不是可用的密钥
        Case("s3-x25519-pkcs8", "deploy/k.json", '{"1": "' + "MC4CAQAwBQYDK2Vu" + "BCIEI" + fake_token(43, "TESTONLY") + '"}\n',
             {"S3"}, set(), {"S3"}),
        # 公钥（SPKI，MCowBQYDK2VuAyEA 开头）不拦
        Case("s3-x25519-pub-neg", "deploy/p.json", '{"1": "' + "MCowBQYDK2VuAyEA" + fake_token(44, "TESTONLY") + '"}\n',
             set(), set(), set()),
        Case("s3-seal-key-file", "deploy/secrets/data_licence_seal_private_keys", "{}\n", {"S3"}, set(), {"S3"}),
        Case("s3-seal-key-file-bak", "backup/data_licence_seal_private_keys.20261102", "x\n", {"S3"}, set(), {"S3"}),
        Case("s3-seal-pub-file-neg", "deploy/secrets/data_licence_seal_public_keys", "{}\n", set(), set(), set()),
        # T-O09a：私钥容器 / 证书文件按文件名拦（.gitignore 不再按“词”忽略）；同名源码不误报
        Case("s3-key-file", "deploy/tls/server.key", "x\n", {"S3"}, set(), {"S3"}),
        Case("s3-key-file-p12", "certs/client.P12", "x\n", {"S3"}, set(), {"S3"}),
        Case("s3-key-file-ssh", "home/.ssh/id_ed25519", "x\n", {"S3"}, set(), {"S3"}),
        Case("s3-key-file-pub-neg", "home/.ssh/id_ed25519.pub", "x\n", set(), set(), set()),
        Case("s3-key-file-src-neg", "src/backend/app/licences/keys.py", "x = 1\n", set(), set(), set()),
        Case("s1-licence-file", "deploy/mairui.lic", "x\n", {"S1"}, set(), {"S1"}),
        Case("s1-licence-file-ext", "backup/user.licence", "x\n", {"S1"}, set(), {"S1"}),
        Case("s1-licence-file-mairui", "deploy/MAIRUI_LICENCE.txt", "x\n", {"S1"}, set(), {"S1"}),
        Case("s1-licence-file-mairui-noext", "tmp/mairui-license", "x\n", {"S1"}, set(), {"S1"}),
        Case("s1-licence-ts-neg", "src/frontend/src/mocks/licence.ts", "export const a = 1;\n", set(), set(), set()),
        Case("s1-licence-py-neg", "src/backend/app/licences/mairui_licence_client.py", "x = 1\n", set(), set(), set()),
        Case("s1-licence-md-neg", "LICENSE", "MIT\n", set(), set(), set()),
        # S4
        Case("s4-envfile", "deploy/.env.local", "FOO=bar\n", {"S4"}, set(), {"S4"}),
        Case("s4-example-real", "deploy/.env.example", "POSTGRES_" + "PASSWORD=" + "notaplaceholder1\n", {"S4"}, set(), {"S4"}),
        Case("s4-example-seal-key", "deploy/y/.env.example", "DATA_LICENCE_SEAL_" + "PRIVATE_KEYS=" + "notaplaceholder1\n",
             {"S4"}, set(), {"S4"}),
        Case(
            "s4-example-neg",
            "deploy/x/.env.example",
            "POSTGRES_PASSWORD=changeme-local\nAPP_MASTER_KEY=\nMAIRUI_LICENCE=<licence>\nDATA_LICENCE_SEAL_PRIVATE_KEYS=\nDEEPSEEK_API_KEY=example-key\nLOG_LEVEL=info\n",
            set(), set(), set(),
        ),
        # S5
        Case("s5", "src/j.py", "acct = '" + "B" + "123456789" + "'\n", {"S5"}, set(), {"S5"}),
        Case("s5-neg-allowlisted", "src/k.py", "acct = 'A" + "000000001'\n", set(), set(), set()),
        Case("s5-neg-stock", "src/l.py", "code = '600000'\n", set(), set(), set()),
        # S6
        Case("s6-sameline", "src/m.txt", HOLDER + FULLWIDTH_COLON + "0" + "123456789\n", {"S6"}, set(), {"S6"}),
        Case("s6-header", "src/n.txt", HOLDER + "\n" + "x\n" * 5 + "v 0" + "123456789\n", {"S6"}, set(), set()),
        Case("s6-neg-nocontext", "src/o.txt", "ts 0" + "123456789\n", set(), set(), set()),
        Case("s6-neg-allowlisted", "src/p.txt", HOLDER + " 0" + "000000001\n", set(), set(), set()),
        # S7
        Case("s7", "data/x.csv", ",".join(W[:3]) + "\n", {"S7"}, set(), {"S7"}),
        Case("s7-docs-top-exempt", "docs/rules.md", ",".join(W[:3]) + "\n", set(), set(), set()),
        Case("s7-docs-sub-not-exempt", "docs/strategies/r.md", ",".join(W[:3]) + "\n", {"S7"}, set(), {"S7"}),
        Case("s7-fixture-dir-exempt", "tests/fixtures/broker_statements/fmt_z/README.md", ",".join(W[:3]) + "\n",
             set(), set(), set()),
        Case("s7-file-level", "data/y.md", W[0] + "\n" + W[1] + "\n" + W[2] + "\n", {"S7"}, set(), set()),
        Case("s7-neg-two-words", "data/z.csv", ",".join(W[:2]) + "\n", set(), set(), set()),
        # S8
        Case("s8-id", "src/q.txt", "id " + fake_id(True) + "\n", {"S8"}, set(), {"S8"}),
        # 校验位错误：secret_scan.py 不阻断；gitleaks 只看出生日期结构，仍会命中（更严格，属预期）
        Case("s8-id-neg-bad-checksum", "src/r.txt", "n " + fake_id(False) + "\n", set(), set(), {"S8"}),
        Case("s8-phone-warn", "src/s.txt", "tel 1" + "3812345678\n", set(), {"S8"}, set()),
        Case("s8-phone-neg", "src/t.txt", "n 1" + "2812345678\n", set(), set(), set()),
        # S9
        Case("s9-account", "src/u.txt", ACCOUNT + FULLWIDTH_COLON + "12345678\n", {"S9"}, set(), {"S9"}),
        Case("s9-account-neg", "src/v.txt", ACCOUNT + FULLWIDTH_COLON + "<masked>\n", set(), set(), set()),
        Case("s9-card-warn", "src/w.txt", "card " + fake_card() + "\n", set(), {"S9"}, set()),
        Case("s9-card-neg", "src/x.txt", "n " + fake_card()[:-1] + str((int(fake_card()[-1]) + 1) % 10) + "\n", set(), set(), set()),
        # 允许清单
        Case("allow-plan-key", "docs/sub/e.md", "evidence_key = " + '"quote.600519.SH.close"' + "\n", set(), set(), set()),
    ]
    return c
