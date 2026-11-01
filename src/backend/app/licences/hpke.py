"""RFC 9180 HPKE，Base 模式（mode_base = 0x00）单次加密/解密，固定套件：

- KEM  ``DHKEM(X25519, HKDF-SHA256)`` = 0x0020
- KDF  ``HKDF-SHA256`` = 0x0001
- AEAD ``AES-256-GCM`` = 0x0002
  （测试可选 ``AES-128-GCM`` = 0x0001，用于对照 RFC 9180 附录 A.1 向量）

为什么不用 ``cryptography.hazmat.primitives.hpke``：其公开接口（cryptography 50）不支持 AAD，
而 plan §2.1B 要求把 ``user_id / row_id / key_version`` 绑定进 AAD（防密文换行/换人）。这里用
X25519、HKDF、AESGCM 原语按 RFC 9180 §4–§6 实现单次 ``Seal``/``Open``
（序号 0，``nonce = base_nonce``）。已用 RFC 9180 附录 A.1.1 向量核对，并与 cryptography 库
内部带 AAD 的实现双向互通（见 T-B45 报告）。

密文格式：``enc (32 字节临时公钥) || AEAD 密文（含 16 字节标签）``。
"""

from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

KEM_X25519_HKDF_SHA256: Final = 0x0020
KDF_HKDF_SHA256: Final = 0x0001
AEAD_AES_128_GCM: Final = 0x0001
AEAD_AES_256_GCM: Final = 0x0002

_NK: Final = {AEAD_AES_128_GCM: 16, AEAD_AES_256_GCM: 32}
_NN: Final = 12
_NH: Final = 32
_NENC: Final = 32
_TAG: Final = 16
_MODE_BASE: Final = b"\x00"
_VERSION_LABEL: Final = b"HPKE-v1"


class HpkeError(Exception):
    """解封失败（密钥不对、AAD 不对、密文被改）。消息不含任何密钥或明文。"""


def _i2osp(n: int, length: int) -> bytes:
    return n.to_bytes(length, "big")


def _extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt or b"\x00" * _NH, ikm, sha256).digest()


def _expand(prk: bytes, info: bytes, length: int) -> bytes:
    return HKDFExpand(algorithm=hashes.SHA256(), length=length, info=info).derive(prk)


def _labeled_extract(suite_id: bytes, salt: bytes, label: bytes, ikm: bytes) -> bytes:
    return _extract(salt, _VERSION_LABEL + suite_id + label + ikm)


def _labeled_expand(suite_id: bytes, prk: bytes, label: bytes, info: bytes, length: int) -> bytes:
    labeled_info = _i2osp(length, 2) + _VERSION_LABEL + suite_id + label + info
    return _expand(prk, labeled_info, length)


_KEM_SUITE: Final = b"KEM" + _i2osp(KEM_X25519_HKDF_SHA256, 2)


def _raw_public(key: X25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _kem_shared_secret(dh: bytes, enc: bytes, pk_rm: bytes) -> bytes:
    eae_prk = _labeled_extract(_KEM_SUITE, b"", b"eae_prk", dh)
    return _labeled_expand(_KEM_SUITE, eae_prk, b"shared_secret", enc + pk_rm, _NH)


def _key_schedule(shared_secret: bytes, info: bytes, aead_id: int) -> tuple[bytes, bytes]:
    suite_id = (
        b"HPKE"
        + _i2osp(KEM_X25519_HKDF_SHA256, 2)
        + _i2osp(KDF_HKDF_SHA256, 2)
        + _i2osp(aead_id, 2)
    )
    psk_id_hash = _labeled_extract(suite_id, b"", b"psk_id_hash", b"")
    info_hash = _labeled_extract(suite_id, b"", b"info_hash", info)
    context = _MODE_BASE + psk_id_hash + info_hash
    secret = _labeled_extract(suite_id, shared_secret, b"secret", b"")
    key = _labeled_expand(suite_id, secret, b"key", context, _NK[aead_id])
    base_nonce = _labeled_expand(suite_id, secret, b"base_nonce", context, _NN)
    return key, base_nonce


def seal(
    pk_r: X25519PublicKey,
    *,
    info: bytes,
    aad: bytes,
    plaintext: bytes,
    aead_id: int = AEAD_AES_256_GCM,
    _sk_e: X25519PrivateKey | None = None,
) -> bytes:
    """``SealBase`` 单次加密，返回 ``enc || ct``。``_sk_e`` 只供测试向量使用。"""
    if aead_id not in _NK:
        raise ValueError("unsupported AEAD")
    sk_e = _sk_e or X25519PrivateKey.generate()
    enc = _raw_public(sk_e.public_key())
    dh = sk_e.exchange(pk_r)
    shared = _kem_shared_secret(dh, enc, _raw_public(pk_r))
    key, nonce = _key_schedule(shared, info, aead_id)
    return enc + AESGCM(key).encrypt(nonce, plaintext, aad)


def open_(
    sk_r: X25519PrivateKey,
    sealed: bytes,
    *,
    info: bytes,
    aad: bytes,
    aead_id: int = AEAD_AES_256_GCM,
) -> bytes:
    """``OpenBase`` 单次解密。任何失败都抛 :class:`HpkeError`（不区分原因）。"""
    if aead_id not in _NK:
        raise ValueError("unsupported AEAD")
    if len(sealed) < _NENC + _TAG:
        raise HpkeError("sealed payload too short")
    enc, ct = sealed[:_NENC], sealed[_NENC:]
    try:
        pk_e = X25519PublicKey.from_public_bytes(enc)
        dh = sk_r.exchange(pk_e)
        shared = _kem_shared_secret(dh, enc, _raw_public(sk_r.public_key()))
        key, nonce = _key_schedule(shared, info, aead_id)
        return AESGCM(key).decrypt(nonce, ct, aad)
    except Exception as exc:  # InvalidTag / ValueError（全零共享密钥等）
        raise HpkeError("hpke open failed") from exc
