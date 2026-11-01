"""密码哈希与口令规则（plan §3.6；参数来自 ``config/auth.yaml``，review-T-B03 M4）。

- 哈希：argon2id，参数取 ``auth.yaml password_hash``（默认 memory 64 MiB、time 3、parallelism 1，
  OWASP 下限由配置模型校验）。改参数后新哈希用新参数，旧哈希在下次登录成功时透明升级
  （:meth:`PasswordPolicy.needs_rehash`）。
- 口令规则：长度取 ``auth.yaml password``（默认 10–128）、至少含字母和数字、不得与用户名相同、
  不在常见弱口令表内。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from app.config_files import AuthConfig

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


class PasswordPolicy:
    """按 ``auth.yaml`` 构造的哈希器与口令规则；用 :func:`policy_for` 取缓存实例。"""

    def __init__(
        self,
        *,
        memory_kib: int,
        time_cost: int,
        parallelism: int,
        hash_len: int,
        salt_len: int,
        min_len: int,
        max_len: int,
    ) -> None:
        self.min_len = min_len
        self.max_len = max_len
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_kib,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
            type=Type.ID,
        )
        #: 用户名不存在时也跑一次校验（同参数），使响应时间与“密码错误”接近，减少用户名探测
        self._dummy_hash = self._hasher.hash("dummy-password-for-timing-0")

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        """哈希缺失或格式不对一律当作不匹配（不抛异常）；缺失时仍跑一次哈希。"""
        try:
            ok = self._hasher.verify(password_hash or self._dummy_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        return ok and password_hash is not None

    def burn(self, password: str) -> None:
        """只消耗一次校验时间（不返回结果），用于不该泄露“是否走到校验”的分支。"""
        self.verify(None, password)

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except (InvalidHashError, ValueError):
            return True

    def issues(self, password: str, *, username: str | None) -> list[str]:
        """返回不满足的规则（英文短语，用作 ``details.fields[].issue``）；空列表即通过。"""
        found: list[str] = []
        if len(password) < self.min_len:
            found.append(f"must be at least {self.min_len} characters")
        if len(password) > self.max_len:
            found.append(f"must be at most {self.max_len} characters")
        if not (_LETTER.search(password) and _DIGIT.search(password)):
            found.append("must contain both letters and digits")
        if username is not None and password.strip().lower() == username.strip().lower():
            found.append("must not equal username")
        if password.lower() in WEAK_PASSWORDS:
            found.append("too common")
        return found


@lru_cache(maxsize=4)
def _policy(params: tuple[int, int, int, int, int, int, int]) -> PasswordPolicy:
    m, t, p, hl, sl, lo, hi = params
    return PasswordPolicy(
        memory_kib=m, time_cost=t, parallelism=p, hash_len=hl, salt_len=sl, min_len=lo, max_len=hi
    )


def policy_for(cfg: AuthConfig) -> PasswordPolicy:
    """按配置取（缓存的）:class:`PasswordPolicy`；参数相同的配置共用一个实例。"""
    h, pw = cfg.password_hash, cfg.password
    return _policy(
        (h.memory_kib, h.time_cost, h.parallelism, h.hash_len, h.salt_len, pw.min_len, pw.max_len)
    )
