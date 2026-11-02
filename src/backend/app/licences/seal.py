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
- 冷却指纹（T-B03e，契约 v0.2.8 #13 补充）：
  ``cooldown_fingerprint = HMAC-SHA256(K2, user_id || 0x00 || licence_hmac)``，
  ``K2 = HKDF-SHA256(APP_MASTER_KEY, info="data-licence-cooldown-fp-v1")``。
  api 拿不到明文（只有 ingest 能解封），DELETE 时只能从去重 HMAC 派生；PUT 时由明文先算去重 HMAC
  再派生，两边一致。与去重 HMAC 不同值、绑定用户，只存在 ``app.user_data_licence_cooldowns``，
  恢复、换证或到期后删除；不对外返回。
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

from app.config import Settings, master_key_bytes
from app.licences import hpke

HPKE_INFO: Final = b"aia/data-licence/v1"
AAD_PREFIX: Final = "mairui-licence|v1|"
DEDUP_INFO: Final = b"data-licence-dedup-v1"
COOLDOWN_FP_INFO: Final = b"data-licence-cooldown-fp-v1"
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


def _derive(settings: Settings, info: bytes) -> bytes:
    # T-B49：非 local/test 无主密钥 → MasterKeyMissingError（不回退到临时密钥）
    master = master_key_bytes(settings)
    if master is None:
        return hmac.new(_EPHEMERAL_DEDUP_KEY, info, hashlib.sha256).digest()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)


def dedup_key(settings: Settings) -> bytes:
    if master_key_bytes(settings) is None:
        return _EPHEMERAL_DEDUP_KEY
    return _derive(settings, DEDUP_INFO)


def licence_hmac(settings: Settings, licence: str) -> bytes:
    return hmac.new(dedup_key(settings), licence.encode("utf-8"), hashlib.sha256).digest()


def cooldown_fingerprint(settings: Settings, user_id: uuid.UUID, dedup_digest: bytes) -> bytes:
    """删除后重提的冷却判定用指纹（带密钥、绑定用户；不存明文，也不等于去重 HMAC）。

    ``dedup_digest`` 是 :func:`licence_hmac` 的结果（DELETE 时取自证书行，PUT 时由明文算出）。"""
    msg = str(user_id).encode("ascii") + b"\x00" + dedup_digest
    return hmac.new(_derive(settings, COOLDOWN_FP_INFO), msg, hashlib.sha256).digest()
