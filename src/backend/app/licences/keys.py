"""封装密钥文件的解析（运维 T-O09 ``deploy/scripts/seal-keygen.sh`` 的格式）。

文件内容是单行 JSON ``{"<key_version>": "<base64 DER>"}``：公钥为 SubjectPublicKeyInfo DER，
私钥为 PKCS#8 DER。容器内路径 ``/run/secrets/data_licence_seal_public_keys`` /
``/run/secrets/data_licence_seal_private_keys``；同名环境变量（大写）优先于文件。

- **api 只加载公钥**（只能加密）。api 进程发现私钥存在时拒绝启动（:func:`private_keys_present`）。
- **私钥只给 ingest**：:func:`load_private_keys` 不经过 :class:`app.config.Settings`，避免私钥
  出现在 api 的配置对象里。

所有错误消息只说哪里不对，不含任何密钥内容。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    load_der_private_key,
    load_der_public_key,
)

SECRETS_DIR_ENV: Final = "SECRETS_DIR"
DEFAULT_SECRETS_DIR: Final = Path("/run/secrets")
PUBLIC_KEYS_NAME: Final = "data_licence_seal_public_keys"
PRIVATE_KEYS_NAME: Final = "data_licence_seal_private_keys"
KEY_VERSION_ENV: Final = "DATA_LICENCE_SEAL_KEY_VERSION"


class SealKeyError(ValueError):
    """密钥文件格式不对。消息不含密钥内容。"""


def secrets_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    raw = env.get(SECRETS_DIR_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_SECRETS_DIR


def read_secret(
    name: str, environ: Mapping[str, str] | None = None, directory: Path | None = None
) -> str | None:
    """环境变量 ``NAME``（大写）优先，其次 ``<secrets_dir>/<name>`` 文件；都没有返回 None。"""
    env = os.environ if environ is None else environ
    value = env.get(name.upper(), "").strip()
    if value:
        return value
    path = (directory or secrets_dir(env)) / name
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SealKeyError(f"无法读取 {name}（{type(exc).__name__}）") from None
    return text or None


def _parse_map(text: str, name: str) -> dict[int, bytes]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise SealKeyError(f"{name} 不是合法 JSON") from None
    if not isinstance(raw, dict) or not raw:
        raise SealKeyError(f"{name} 必须是非空 JSON 对象 {{版本号: base64 DER}}")
    result: dict[int, bytes] = {}
    for k, v in raw.items():
        if not (isinstance(k, str) and k.isdigit() and int(k) >= 1):
            raise SealKeyError(f"{name} 的版本号必须是正整数")
        if not isinstance(v, str):
            raise SealKeyError(f"{name} 版本 {k} 的值必须是 base64 字符串")
        try:
            result[int(k)] = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError):
            raise SealKeyError(f"{name} 版本 {k} 不是合法 base64") from None
    return result


def parse_public_keys(text: str) -> dict[int, X25519PublicKey]:
    keys: dict[int, X25519PublicKey] = {}
    for version, der in _parse_map(text, PUBLIC_KEYS_NAME).items():
        try:
            key = load_der_public_key(der)
        except ValueError:
            raise SealKeyError(f"{PUBLIC_KEYS_NAME} 版本 {version} 不是 SPKI DER 公钥") from None
        if not isinstance(key, X25519PublicKey):
            raise SealKeyError(f"{PUBLIC_KEYS_NAME} 版本 {version} 不是 X25519 公钥")
        keys[version] = key
    return keys


def parse_private_keys(text: str) -> dict[int, X25519PrivateKey]:
    keys: dict[int, X25519PrivateKey] = {}
    for version, der in _parse_map(text, PRIVATE_KEYS_NAME).items():
        try:
            key = load_der_private_key(der, password=None)
        except (ValueError, TypeError):
            raise SealKeyError(f"{PRIVATE_KEYS_NAME} 版本 {version} 不是 PKCS#8 DER 私钥") from None
        if not isinstance(key, X25519PrivateKey):
            raise SealKeyError(f"{PRIVATE_KEYS_NAME} 版本 {version} 不是 X25519 私钥")
        keys[version] = key
    return keys


def private_keys_present(
    environ: Mapping[str, str] | None = None, directory: Path | None = None
) -> bool:
    """api 启动自检：私钥（环境变量或 secrets 文件）存在 → True。只看是否存在，不读内容。"""
    env = os.environ if environ is None else environ
    if env.get(PRIVATE_KEYS_NAME.upper(), "").strip():
        return True
    return ((directory or secrets_dir(env)) / PRIVATE_KEYS_NAME).exists()


def load_private_keys(
    environ: Mapping[str, str] | None = None, directory: Path | None = None
) -> dict[int, X25519PrivateKey]:
    """**仅 ingest 调用**：加载全部版本的私钥（轮换期间旧版本仍可解封）。未配置 → 空字典。"""
    text = read_secret(PRIVATE_KEYS_NAME, environ, directory)
    return parse_private_keys(text) if text else {}
