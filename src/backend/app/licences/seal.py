"""证书封装/解封与去重 HMAC（plan §2.1B，T-A07）。

- 封装：HPKE Base（见 :mod:`.hpke`），``info = b"aia/data-licence/v1"``，
  ``AAD = "mairui-licence|v1|" + user_id + "|" + row_id + "|" + key_version``（UUID 小写带连字符，
  版本号十进制）。密文与 ``seal_key_version`` 一起入库；行号/用户号写进 AAD，密文搬到别的行或别的
  用户名下都解不开。
- 去重：``licence_hmac = HMAC-SHA256(K, licence)``，
  ``K = HKDF-SHA256(APP_MASTER_KEY, info="data-licence-dedup-v1")``，
  只用于“同一证书不能绑两个账号”（部分唯一索引）。不对外返回，也不作为指纹显示。
  未配置 ``APP_MASTER_KEY``（只允许 local/test）时用进程内临时密钥（与分页游标同口径；重启后
  旧行的去重失效，仅开发环境）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings
from app.licences import hpke

HPKE_INFO: Final = b"aia/data-licence/v1"
AAD_PREFIX: Final = "mairui-licence|v1|"
DEDUP_INFO: Final = b"data-licence-dedup-v1"
#: 进程内临时去重密钥：仅 local/test 且未设置 APP_MASTER_KEY 时使用
_EPHEMERAL_DEDUP_KEY: Final = secrets.token_bytes(32)


def aad(user_id: uuid.UUID, row_id: uuid.UUID, key_version: int) -> bytes:
    return f"{AAD_PREFIX}{user_id}|{row_id}|{key_version}".encode("ascii")


def seal_licence(
    public_key: X25519PublicKey,
    licence: str,
    *,
    user_id: uuid.UUID,
    row_id: uuid.UUID,
    key_version: int,
) -> bytes:
    return hpke.seal(
        public_key,
        info=HPKE_INFO,
        aad=aad(user_id, row_id, key_version),
        plaintext=licence.encode("utf-8"),
    )


def open_licence(
    private_key: X25519PrivateKey,
    sealed: bytes,
    *,
    user_id: uuid.UUID,
    row_id: uuid.UUID,
    key_version: int,
) -> str:
    """**仅 ingest**：解封。失败抛 :class:`app.licences.hpke.HpkeError`（不含明文）。"""
    raw = hpke.open_(private_key, sealed, info=HPKE_INFO, aad=aad(user_id, row_id, key_version))
    return raw.decode("utf-8")


def dedup_key(settings: Settings) -> bytes:
    if settings.app_master_key is None:
        return _EPHEMERAL_DEDUP_KEY
    master = settings.app_master_key.get_secret_value().encode("utf-8")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=DEDUP_INFO).derive(master)


def licence_hmac(settings: Settings, licence: str) -> bytes:
    return hmac.new(dedup_key(settings), licence.encode("utf-8"), hashlib.sha256).digest()
