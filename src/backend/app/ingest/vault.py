"""ingest 进程内的证书解封与脱敏（plan §2.1B 第 1 点）。

- 私钥只在 ingest 注入（:func:`app.licences.keys.load_private_keys`，``/run/secrets``）；
  按行的 ``seal_key_version`` 选私钥，AAD 绑定 ``user_id``/``row_id``/``key_version``。
- 明文只放在本对象的内存字典里，不写 Redis、不写库、不写日志；``repr`` 不含明文。
- :meth:`redact`：对已加载的**全部**证书明文做字符串替换（日志、异常、留存的上游响应）。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.licences.hpke import HpkeError
from app.licences.keys import load_private_keys
from app.licences.seal import open_licence

MASK = "***"


class VaultError(Exception):
    """解封失败（缺版本私钥、密文损坏或被挪行）。消息不含任何证书或密文内容。"""


@dataclass(frozen=True)
class SealedLicence:
    licence_id: uuid.UUID
    user_id: uuid.UUID
    ciphertext: bytes
    key_version: int


class LicenceVault:
    def __init__(self, private_keys: Mapping[int, X25519PrivateKey]) -> None:
        self._keys = dict(private_keys)
        self._plain: dict[uuid.UUID, str] = {}

    @classmethod
    def from_secrets(cls) -> LicenceVault:
        return cls(load_private_keys())

    def __repr__(self) -> str:
        return f"LicenceVault(versions={sorted(self._keys)}, loaded={len(self._plain)})"

    @property
    def key_versions(self) -> list[int]:
        return sorted(self._keys)

    def open(self, row: SealedLicence) -> str:
        key = self._keys.get(row.key_version)
        if key is None:
            raise VaultError(f"no private key for seal_key_version={row.key_version}")
        try:
            plain = open_licence(
                key,
                row.ciphertext,
                user_id=row.user_id,
                row_id=row.licence_id,
                key_version=row.key_version,
            )
        except HpkeError as exc:
            raise VaultError(f"cannot open licence_id={row.licence_id}") from exc
        self._plain[row.licence_id] = plain
        return plain

    def get(self, licence_id: uuid.UUID) -> str | None:
        return self._plain.get(licence_id)

    def forget(self, licence_id: uuid.UUID) -> None:
        """证书删除、失效或被替换时调用。"""
        self._plain.pop(licence_id, None)

    def redact(self, text: str) -> str:
        # 长的先替换，避免一个证书是另一个的子串时漏掉尾部
        for plain in sorted(set(self._plain.values()), key=len, reverse=True):
            if plain:
                text = text.replace(plain, MASK)
        return text

    def redact_bytes(self, data: bytes) -> bytes:
        for plain in sorted(set(self._plain.values()), key=len, reverse=True):
            if plain:
                data = data.replace(plain.encode("utf-8"), MASK.encode("ascii"))
        return data


def mask_url(url: str, licence: str) -> str:
    """日志里打印 URL 前调用：证书段替换为 ``***``。"""
    return url.replace(licence, MASK) if licence else url
