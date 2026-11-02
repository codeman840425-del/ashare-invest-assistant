"""导入模块的派生密钥（T-B46）：``HMAC(APP_MASTER_KEY, label)``。

未设置 ``APP_MASTER_KEY`` 时（只有 local/test 允许，见 Settings 校验）使用进程内临时主密钥，
重启后旧数据无法解密 / 旧 HMAC 无法比对——只用于开发与测试。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

from app.config import Settings, master_key_bytes

KEK_LABEL: Final = b"aia/imports/kek/v1"
RAWLINE_LABEL: Final = b"aia/imports/rawline/v1"
HOLDER_LABEL: Final = b"aia/imports/holder/v1"

_EPHEMERAL_MASTER: Final = secrets.token_bytes(32)


def derive(settings: Settings, label: bytes) -> bytes:
    # T-B49：非 local/test 无主密钥 → MasterKeyMissingError（不回退到临时密钥）
    master = master_key_bytes(settings) or _EPHEMERAL_MASTER
    return hmac.new(master, label, hashlib.sha256).digest()
