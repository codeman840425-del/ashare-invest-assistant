"""原始导入文件的加密存储（plan §3.5A，T-B46）。

- 存放在仓库之外：``IMPORT_STORAGE_PATH``；未配置时只有 local/test 退回系统临时目录
  ``<tmp>/aia-imports``，其他环境上传返回 ``503 MAINTENANCE``。
- AES-256-GCM，每文件独立数据密钥（DEK）；DEK 用 ``HMAC(APP_MASTER_KEY, "aia/imports/kek/v1")``
  派生的 KEK 包裹。文件格式：
  ``b"AIA1" | nonce_k(12) | wrapped_dek(48) | nonce_d(12) | ciphertext``，
  AAD = 批次 id。
- ``import_files.storage_path`` 只存相对路径（``<user_id>/<batch_id>.bin``）。
- ``import_rows.raw_line``：**先掩码再加密**（``HMAC(..., "aia/imports/rawline/v1")`` 派生密钥），
  base64 文本 ``v1:<nonce+ct>``；对外只给掩码后的行。
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.importing.keys import KEK_LABEL, RAWLINE_LABEL, derive

MAGIC: Final = b"AIA1"
_DEV_ENVS: Final = frozenset({"local", "test"})


def storage_root(settings: Settings) -> Path:
    if settings.import_storage_path is not None:
        return Path(settings.import_storage_path)
    if settings.app_env in _DEV_ENVS:
        return Path(tempfile.gettempdir()) / "aia-imports"
    raise AppError(ErrorCode.MAINTENANCE)


def encrypt_file(settings: Settings, data: bytes, aad: bytes) -> bytes:
    kek = derive(settings, KEK_LABEL)
    dek = AESGCM.generate_key(bit_length=256)
    nonce_k, nonce_d = os.urandom(12), os.urandom(12)
    wrapped = AESGCM(kek).encrypt(nonce_k, dek, aad)
    return MAGIC + nonce_k + wrapped + nonce_d + AESGCM(dek).encrypt(nonce_d, data, aad)


def decrypt_file(settings: Settings, blob: bytes, aad: bytes) -> bytes:
    if blob[:4] != MAGIC:
        raise ValueError("bad magic")
    kek = derive(settings, KEK_LABEL)
    nonce_k, wrapped = blob[4:16], blob[16:64]
    nonce_d, ct = blob[64:76], blob[76:]
    dek = AESGCM(kek).decrypt(nonce_k, wrapped, aad)
    return AESGCM(dek).decrypt(nonce_d, ct, aad)


def write_raw(settings: Settings, user_id: str, batch_id: str, data: bytes) -> str:
    """加密写入，返回相对路径。目录 0700、文件 0600。"""
    root = storage_root(settings)
    rel = f"{user_id}/{batch_id}.bin"
    path = root / rel
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    blob = encrypt_file(settings, data, batch_id.encode())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob)
    return rel


def read_raw(settings: Settings, rel: str, batch_id: str) -> bytes:
    root = storage_root(settings).resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise ValueError("path escapes storage root")
    return decrypt_file(settings, path.read_bytes(), batch_id.encode())


def delete_raw(settings: Settings, rel: str) -> None:
    """放弃批次时删除加密原始文件（不存在则忽略）。"""
    root = storage_root(settings).resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise ValueError("path escapes storage root")
    path.unlink(missing_ok=True)


def encrypt_line(settings: Settings, masked: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(derive(settings, RAWLINE_LABEL)).encrypt(nonce, masked.encode("utf-8"), None)
    return "v1:" + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_line(settings: Settings, value: str | None) -> str:
    if not value or not value.startswith("v1:"):
        return ""
    raw = base64.b64decode(value[3:])
    return AESGCM(derive(settings, RAWLINE_LABEL)).decrypt(raw[:12], raw[12:], None).decode("utf-8")
