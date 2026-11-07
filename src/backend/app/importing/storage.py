"""原始导入文件的加密存储（plan §3.5A，T-B46）。

- 存放在仓库之外：``IMPORT_STORAGE_PATH``；未配置时只有 local/test 退回系统临时目录
  ``<tmp>/aia-imports``，其他环境上传返回 ``503 MAINTENANCE``。
- 根目录解析由 :func:`resolve_imports_root` 统一完成，API（:func:`storage_root`）与注销 CLI
  （``app.cli.delete_user_data.imports_root``）共用（评审 bbf58a0 m7）。
- AES-256-GCM，每文件独立数据密钥（DEK）；DEK 用 ``HMAC(APP_MASTER_KEY, "aia/imports/kek/v1")``
  派生的 KEK 包裹。当前写入格式（评审 bbf58a0 m8）：
  ``b"AIA2" | kek_id(8) | nonce_k(12) | wrapped_dek(48) | nonce_d(12) | ciphertext``，
  ``kek_id = HMAC(KEK, "aia/imports/kek-id/v1")[:8]``（不泄露 KEK，仅用于识别用的是哪把 KEK），
  AAD = 批次 id。旧格式 ``b"AIA1" | nonce_k | wrapped_dek | nonce_d | ct``（无 kek_id）仍可读。
  kek_id 与当前 KEK 不符时抛 :class:`KekMismatchError`（而不是含糊的 GCM 认证失败），供主密钥轮换
  时识别旧文件；轮换方案见 reports/T-B46-x.md。
- ``import_files.storage_path`` 只存相对路径（``<user_id>/<batch_id>.bin``）。
- ``import_rows.raw_line``：**先掩码再加密**（``HMAC(..., "aia/imports/rawline/v1")`` 派生密钥），
  base64 文本 ``v1:<nonce+ct>``；对外只给掩码后的行。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import tempfile
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.importing.keys import KEK_LABEL, RAWLINE_LABEL, derive

MAGIC_V1: Final = b"AIA1"
MAGIC: Final = b"AIA2"
KEK_ID_LABEL: Final = b"aia/imports/kek-id/v1"
KEK_ID_LEN: Final = 8
_DEV_ENVS: Final = frozenset({"local", "test"})
#: 注销 CLI 在非 local/test 且未配置 ``IMPORT_STORAGE_PATH`` 时的默认根目录（与部署卷一致）
DEFAULT_IMPORTS_DIR: Final = "/srv/aia/imports"


class KekMismatchError(ValueError):
    """文件头的 kek_id 与当前 KEK 不一致（主密钥已轮换，或文件来自其他环境）。"""


def resolve_imports_root(storage_path: str | os.PathLike[str] | None, app_env: str) -> Path | None:
    """原始导入文件根目录：``IMPORT_STORAGE_PATH``；未配置时 local/test 用 ``<tmp>/aia-imports``；
    其他环境返回 ``None``（API 据此返回 503，CLI 退回 :data:`DEFAULT_IMPORTS_DIR`）。"""
    if storage_path is not None and str(storage_path) != "":
        return Path(storage_path)
    if app_env in _DEV_ENVS:
        return Path(tempfile.gettempdir()) / "aia-imports"
    return None


class StorageRootMissingError(FileNotFoundError):
    """原始导入文件存储根目录不存在（不含路径，避免日志泄露部署布局）。"""


def storage_root(settings: Settings) -> Path:
    root = resolve_imports_root(settings.import_storage_path, settings.app_env)
    if root is None:
        raise AppError(ErrorCode.MAINTENANCE)
    return root


def kek_id(kek: bytes) -> bytes:
    return hmac.new(kek, KEK_ID_LABEL, hashlib.sha256).digest()[:KEK_ID_LEN]


def encrypt_file(settings: Settings, data: bytes, aad: bytes) -> bytes:
    kek = derive(settings, KEK_LABEL)
    dek = AESGCM.generate_key(bit_length=256)
    nonce_k, nonce_d = os.urandom(12), os.urandom(12)
    wrapped = AESGCM(kek).encrypt(nonce_k, dek, aad)
    ct = AESGCM(dek).encrypt(nonce_d, data, aad)
    return MAGIC + kek_id(kek) + nonce_k + wrapped + nonce_d + ct


def file_kek_id(blob: bytes) -> bytes | None:
    """读取文件头里的 kek_id（旧格式 AIA1 没有，返回 ``None``）。"""
    if blob[:4] == MAGIC:
        return blob[4 : 4 + KEK_ID_LEN]
    if blob[:4] == MAGIC_V1:
        return None
    raise ValueError("bad magic")


def decrypt_file(settings: Settings, blob: bytes, aad: bytes) -> bytes:
    kek = derive(settings, KEK_LABEL)
    fid = file_kek_id(blob)
    if fid is not None:
        if not hmac.compare_digest(fid, kek_id(kek)):
            raise KekMismatchError("import file was encrypted with a different KEK")
        body = blob[4 + KEK_ID_LEN :]
    else:
        body = blob[4:]
    nonce_k, wrapped = body[:12], body[12:60]
    nonce_d, ct = body[60:72], body[72:]
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
    """删除加密原始文件（不存在则忽略）。

    契约 #35 起放弃批次不再调用；只由 retained_until 到期清理（T-B56）使用。

    存储根目录不存在（如 worker 没挂 imports 卷）→ 抛 :class:`StorageRootMissingError`，
    **不**当作已删除（契约 v0.2.9 #41 / review-028c077 M2）；调用方保留该行下轮重试。
    根目录存在而文件不存在才视为已删除。"""
    root = storage_root(settings).resolve()
    if not root.is_dir():
        raise StorageRootMissingError("import storage root does not exist")
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
