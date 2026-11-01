"""同意条款键（契约 §7.1）与 ``app.consents.kind``（plan §3.3）的对应关系。

- ``POST /me/consents`` 的 ``key``：契约只列 ``signal_risk_disclosure`` / ``privacy`` / ``terms``。
  ``privacy`` → ``privacy_policy``；``terms``（用户协议）在 plan §3.3 的 kind 中没有
  → 迁移 0004 补入。
- 注册 ``agreements``：plan §3.6“必须勾选用户协议/隐私政策/风险揭示” → 必须恰好覆盖
  ``terms``、``privacy``、``risk_disclosure``（契约未列取值，按 plan 取名，见报告）。
- ``GET /me`` 的 ``consents``：每种 kind 取最新一行，``granted=true`` 才列出；键用契约名
  （``privacy_policy`` 显示为 ``privacy``），其余 kind 原名输出。
"""

from __future__ import annotations

from typing import Final

API_TO_KIND: Final[dict[str, str]] = {
    "signal_risk_disclosure": "signal_risk_disclosure",
    "privacy": "privacy_policy",
    "terms": "terms",
}
KIND_TO_API: Final[dict[str, str]] = {v: k for k, v in API_TO_KIND.items()}

REGISTER_AGREEMENT_TO_KIND: Final[dict[str, str]] = {
    "terms": "terms",
    "privacy": "privacy_policy",
    "risk_disclosure": "risk_disclosure",
}

#: 注册时勾选的条款没有版本号来源（全站揭示文案版本归 T-B15）→ 占位，见报告 TODO
REGISTER_DOC_VERSION: Final = "unversioned"
