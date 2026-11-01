"""密码哈希与口令规则（plan §3.6）。

- 哈希：argon2id，memory 64 MiB、time 3、parallelism 1（plan §3.6 的默认值）。plan 说“参数可配置”，
  但 §6.1 / 环境变量表都没有给出键名 → 这里用常量，键名待架构师定（报告 TODO）。
- 登录时 :func:`needs_rehash` 为真则透明升级哈希。
- 口令规则：≥ 10 位、至少含字母和数字、不得与用户名相同、不在常见弱口令表内。
"""

from __future__ import annotations

import re
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

ARGON2_MEMORY_KIB: Final = 64 * 1024
ARGON2_TIME_COST: Final = 3
ARGON2_PARALLELISM: Final = 1

PASSWORD_MIN_LEN: Final = 10
#: 契约没有给上限；argon2 对超长输入无害，但限制请求体大小，取 128（保守，报告注明）
PASSWORD_MAX_LEN: Final = 128

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_KIB,
    parallelism=ARGON2_PARALLELISM,
    type=Type.ID,
)

#: 常见弱口令（小写比较）。plan 只要求“不在常见弱口令表内”，未给出表；先放一份短表，
#: 全部满足“≥10 位且含字母和数字”这一前置条件才有意义。
WEAK_PASSWORDS: Final = frozenset(
    {
        "password123",
        "password1234",
        "qwerty12345",
        "qwerty123456",
        "abc1234567",
        "abcd123456",
        "a123456789",
        "1234567890a",
        "1qaz2wsx3edc",
        "1q2w3e4r5t",
        "zxcvbnm123",
        "iloveyou123",
        "admin12345",
        "admin123456",
        "woaini1314",
        "aa123456789",
        "test123456",
        "passw0rd123",
    }
)

_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")

#: 用户名不存在时也跑一次校验，使响应时间与“密码错误”接近，减少用户名探测
_DUMMY_HASH: Final = _hasher.hash("dummy-password-for-timing-0")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """哈希缺失或格式不对一律当作不匹配（不抛异常）。"""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def password_issues(password: str, *, username: str | None) -> list[str]:
    """返回不满足的规则（英文短语，用作 ``details.fields[].issue``）；空列表即通过。"""
    issues: list[str] = []
    if len(password) < PASSWORD_MIN_LEN:
        issues.append(f"must be at least {PASSWORD_MIN_LEN} characters")
    if len(password) > PASSWORD_MAX_LEN:
        issues.append(f"must be at most {PASSWORD_MAX_LEN} characters")
    if not (_LETTER.search(password) and _DIGIT.search(password)):
        issues.append("must contain both letters and digits")
    if username is not None and password.strip().lower() == username.strip().lower():
        issues.append("must not equal username")
    if password.lower() in WEAK_PASSWORDS:
        issues.append("too common")
    return issues
