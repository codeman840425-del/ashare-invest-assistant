"""应用配置（plan.md §6、§8 T-B01）：环境变量 + ``config/*.yaml``。

- 运行参数（数据库、Redis、密钥、端口等）只来自环境变量，与
  ``deploy/compose/docker-compose.yml`` 中 ``api`` 服务的 ``environment`` 同名。
- 业务配置（``config/realtime.yaml``、``ingest.yaml``、``llm.yaml`` 等九个文件，plan §6.1）
  只读加载到 :attr:`Settings.business`，并按 :mod:`app.config_files` 严格校验：未知键、缺文件、
  多余文件、取值越界 → 启动失败。``config/strategies/`` 子目录不在这里加载：L2 模板要经
  导入器成为不可变 DB 版本，放文件不会激活（plan §2.5.13）。
- 三层优先级与合并口径（plan §6.1，T-A02）：环境变量（只限白名单键）> 管理端运行时覆盖
  （:meth:`Settings.with_business_overrides`）> YAML。三层按 :func:`deep_merge` **深合并**：
  映射逐键递归，列表与标量整体替换，``null`` 视为未覆盖（“值显式为 null 视为未覆盖，不能用来
  删除键”；构造参数 ``Settings(business={...})`` 这一层同样适用）；合并结果再整体走严格校验
  （``extra="forbid"`` + ``schema_version``），未知键出现在任何一层都失败。
- 环境变量白名单（plan §6.1 注明的键）：``INGEST_HEARTBEAT_KEY`` / ``INGEST_PAUSED_KEY`` /
  ``INGEST_STALE_AFTER_S``，以及等价的嵌套写法 ``BUSINESS__INGEST__HEARTBEAT__KEY`` /
  ``…__PAUSED_KEY`` / ``…__STALE_AFTER_S``（分隔符 ``__``）。其他 ``BUSINESS__*`` 或整块
  ``BUSINESS`` 环境变量 → 启动失败（见 :func:`business_env_layer`）。
- 本服务**不读取** ``MAIRUI_LICENCE``。T-A07（plan §2.1B 第 7 点）起生产不再使用全站证书：
  每位用户的证书以 HPKE 密文存库，只有 ``ingest`` 持有解密私钥；``ingest`` 发现
  ``MAIRUI_LICENCE`` 非空即拒绝启动（:mod:`app.workers.ingest`）。未声明的环境变量一律忽略
  （``extra="ignore"``）。
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.config_files import BUSINESS_FILES, BusinessConfig
from app.licences.keys import PUBLIC_KEYS_NAME, SealKeyError, parse_public_keys, read_secret
from app.schemas.enums import RegistrationMode

AppEnv = Literal["local", "test", "staging", "production"]

#: 允许在缺少 APP_MASTER_KEY 时用进程内临时密钥的环境（游标签名重启即失效）
_DEV_ENVS: frozenset[str] = frozenset({"local", "test"})
#: T-B49 / T-O11 裁定：``SERVICE_NAME`` 白名单（与 deploy/compose 一致）；非 local/test 环境出现
#: 白名单外的值拒绝启动（防止拼错名字绕过下面的主密钥要求）。
SERVICE_NAMES: Final = frozenset(
    {"api", "worker", "ingest", "signal-rt", "beat", "cooldown-purge", "migrate", "maint-cli"}
)
#: 只有这些服务持有并要求 ``APP_MASTER_KEY``（非 local/test）
MASTER_KEY_SERVICES: Final = frozenset({"api", "worker"})
#: 这些服务**不得**持有主密钥：发现即拒绝启动（ingest 只持有证书解封私钥，T-O11）
MASTER_KEY_FORBIDDEN_SERVICES: Final = frozenset({"ingest"})


class MasterKeyMissingError(RuntimeError):
    """非 local/test 环境需要派生密钥但没有 ``APP_MASTER_KEY``（不回退到进程内临时密钥）。"""


def master_key_bytes(settings: Settings) -> bytes | None:
    """派生密钥的唯一入口：返回主密钥字节；只有 local/test 且未配置时返回 ``None``（调用方
    才可以用进程内临时密钥），其他环境未配置 → :class:`MasterKeyMissingError`。"""
    if settings.app_master_key is not None:
        return settings.app_master_key.get_secret_value().encode("utf-8")
    if settings.app_env in _DEV_ENVS:
        return None
    raise MasterKeyMissingError(
        f"APP_MASTER_KEY 未配置（APP_ENV={settings.app_env}，SERVICE_NAME={settings.service_name}）"
    )


#: ``TRUSTED_PROXIES`` 默认：回环 + RFC1918（compose 内的 nginx）
_DEFAULT_TRUSTED_PROXIES: Final = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)


def _default_config_dir() -> Path:
    """容器内为 /app/config（compose dev 叠加层挂载点）；源码运行时为仓库根的 config/。"""
    container = Path("/app/config")
    if container.is_dir():
        return container
    return Path(__file__).resolve().parents[3] / "config"


class ConfigError(RuntimeError):
    """配置文件无法解析或结构不符合约定。"""


class _Yaml12BoolLoader(yaml.SafeLoader):
    """布尔只认 ``true``/``false``（YAML 1.2 语义）。

    PyYAML 默认按 YAML 1.1 把 ``on``/``off``/``yes``/``no`` 也解析成布尔，
    ``horizon_classifier.yaml`` 的 ``recompute.on`` 键会因此变成 ``True``。
    """


_Yaml12BoolLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12BoolLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


#: plan §6.1 / §7.4A：licence、密码、密钥只走环境变量；YAML 中出现这类键名直接启动失败（评审 m2）。
#: 复数形式也算（T-B45：``licences.value: <证书>`` 不能漏网）；``tokens`` 例外——
#: llm.yaml 的 ``context_window_tokens`` 等是用量参数。
_SENSITIVE_KEY_PARTS: Final = frozenset(
    {
        "licence",
        "licences",
        "license",
        "licenses",
        "password",
        "passwords",
        "passwd",
        "secret",
        "secrets",
        "token",
        "apikey",
        "credential",
        "credentials",
    }
)


#: 只存**环境变量名**的键：键名以 ``_env`` 结尾、值是环境变量名
#: （如 plan §6.1 llm.yaml 的 ``api_key_env: DEEPSEEK_API_KEY``）。值必须形如
#: ``^[A-Z][A-Z0-9_]*$``，否则（例如把密钥值本身写进来）仍按敏感键拦截。
_ENV_NAME_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _is_env_name_ref(key: str, value: object) -> bool:
    if not key.lower().endswith("_env") or not isinstance(value, str):
        return False
    return bool(_ENV_NAME_RE.match(value))


def _sensitive_key_paths(data: object, path: str = "") -> list[str]:
    """递归找出键名分段（按 ``_`` / ``-`` / ``.`` 切分）命中敏感词的键路径；只返回路径，不含值。

    例外：``*_env`` 键且值是环境变量名（只引用变量名、不含密钥值）不算敏感键，
    见 :func:`_is_env_name_ref`。
    """
    hits: list[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            k = str(key)
            here = f"{path}.{k}" if path else k
            parts = set(re.split(r"[_\-.]", k.lower()))
            sensitive = bool(parts & _SENSITIVE_KEY_PARTS) or "api_key" in k.lower()
            if sensitive and not _is_env_name_ref(k, value):
                hits.append(here)
            hits.extend(_sensitive_key_paths(value, here))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            hits.extend(_sensitive_key_paths(item, f"{path}[{i}]"))
    return hits


#: 键名含敏感词、但只放策略参数的段（plan §6.1 ``auth.yaml``：口令长度、argon2 参数；
#: ``ingest.yaml`` 的 ``licences`` / ``data_sharing``：每证书限额与调度参数，T-A07）。
#: 豁免条件：路径在本表中且所有叶子值都是整数/布尔；仅 :data:`_POLICY_TOKEN_STEMS`
#: 里的文件（``ingest``）另允许**短于 16 个字符**的小写标识（``drr``、``00:01``、
#: ``per_licence``）——麦蕊证书至少 16 个字符（契约 ``PUT /me/data-licence``），装不下。
#: ``auth.yaml`` 的 ``password`` 段仍只认数值：短口令也可能是字符串。
_POLICY_ONLY_PATHS: dict[str, frozenset[str]] = {
    "auth": frozenset({"password", "password_hash"}),
    "ingest": frozenset({"licences", "data_sharing"}),
}

_POLICY_TOKEN_STEMS: Final = frozenset({"ingest"})
_POLICY_TOKEN_RE: Final = re.compile(r"^[a-z0-9_:]{1,15}$")


def _policy_leaves_only(data: object, *, tokens: bool) -> bool:
    if isinstance(data, Mapping):
        return all(_policy_leaves_only(v, tokens=tokens) for v in data.values())
    if isinstance(data, list):
        return all(_policy_leaves_only(v, tokens=tokens) for v in data)
    if isinstance(data, str):
        return tokens and bool(_POLICY_TOKEN_RE.match(data))
    return isinstance(data, bool | int)


def _policy_only(stem: str, data: Mapping[str, Any], hit: str) -> bool:
    top = hit.split(".", 1)[0]
    if top not in _POLICY_ONLY_PATHS.get(stem, frozenset()):
        return False
    return _policy_leaves_only(data.get(top), tokens=stem in _POLICY_TOKEN_STEMS)


def load_yaml_dir(config_dir: Path) -> dict[str, Any]:
    """读取 ``config_dir`` 下一层的 ``*.yaml`` / ``*.yml``（不递归），按文件名排序。

    每个文件顶层必须是映射（或空文件），返回 ``{文件名stem: 内容}``。
    目录不存在时返回空字典（Phase 0 仓库里只有 ``config/strategies/``）。
    """
    if not config_dir.is_dir():
        return {}
    result: dict[str, Any] = {}
    files = sorted(p for p in config_dir.iterdir() if p.is_file() and p.suffix in {".yaml", ".yml"})
    from app.reference_files import REFERENCE_FILES, load_reference_file

    for path in files:
        if path.name in REFERENCE_FILES:
            load_reference_file(config_dir, path.name)
            continue
        if path.stem in result:
            raise ConfigError(f"配置文件重名：{path.stem}（.yaml 与 .yml 同时存在）")
        try:
            with path.open(encoding="utf-8") as fh:
                data = yaml.load(fh, Loader=_Yaml12BoolLoader)  # noqa: S506 - SafeLoader 子类
        except yaml.YAMLError as exc:
            raise ConfigError(f"配置文件解析失败：{path.name}") from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件顶层必须是映射：{path.name}")
        hits = [h for h in _sensitive_key_paths(data) if not _policy_only(path.stem, data, h)]
        if hits:
            raise ConfigError(
                f"配置文件 {path.name} 含疑似敏感键 {hits}：licence/密码/密钥只能走环境变量"
            )
        result[path.stem] = data
    return result


def deep_merge(base: Mapping[str, Any], *overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """按 plan §6.1 合并口径把 ``overrides`` 依次叠到 ``base`` 上（后者优先），返回新字典。

    - 两侧都是映射 → 逐键递归，未覆盖的同级键保留；
    - 列表、标量、类型不同 → 覆盖值整体替换（列表不按元素合并）；
    - 覆盖值为 ``None`` → 视为未覆盖（不能用来删除键）；新增键下嵌套的 ``None`` 一并剔除。

    不修改入参。未知键不在这里拦截：合并结果交给严格模型校验（``extra="forbid"``）。
    """
    result: dict[str, Any] = {k: _copy_tree(v) for k, v in base.items()}
    for layer in overrides:
        if not layer:
            continue
        for key, value in layer.items():
            if value is None:
                continue
            current = result.get(key)
            if isinstance(current, Mapping) and isinstance(value, Mapping):
                result[key] = deep_merge(current, value)
            else:
                result[key] = _strip_none(value)
    return result


def _copy_tree(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _copy_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_tree(v) for v in value]
    return value


def _strip_none(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_copy_tree(v) for v in value]
    return value


#: 环境变量白名单 → business 中的路径（plan §6.1 注明的键；嵌套写法与扁平别名等价）
_BUSINESS_ENV_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "BUSINESS__INGEST__HEARTBEAT__KEY": ("ingest", "heartbeat", "key"),
    "BUSINESS__INGEST__HEARTBEAT__PAUSED_KEY": ("ingest", "heartbeat", "paused_key"),
    "BUSINESS__INGEST__HEARTBEAT__STALE_AFTER_S": ("ingest", "heartbeat", "stale_after_s"),
    "INGEST_HEARTBEAT_KEY": ("ingest", "heartbeat", "key"),
    "INGEST_PAUSED_KEY": ("ingest", "heartbeat", "paused_key"),
    "INGEST_STALE_AFTER_S": ("ingest", "heartbeat", "stale_after_s"),
}


def business_env_layer(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """从环境变量取 business 覆盖层（只认白名单）；返回嵌套字典，供 :func:`deep_merge`。

    出现白名单之外的 ``BUSINESS__*``、或整块 ``BUSINESS`` → :class:`ConfigError`
    （防止拼写错误被静默忽略、也防止整块 JSON 绕过深合并把 YAML 整体顶掉）。
    空字符串视为未设置。同一路径同时给了嵌套写法与扁平别名时取值必须相同，否则失败（F5）。
    错误消息只含变量名，不含取值。
    """
    env = os.environ if environ is None else environ
    upper = {k.upper(): v for k, v in env.items()}
    bad = sorted(
        k
        for k in upper
        if (k == "BUSINESS" or k.startswith("BUSINESS__")) and k not in _BUSINESS_ENV_KEYS
    )
    if bad:
        raise ConfigError(
            f"不允许的业务配置环境变量 {bad}：plan §6.1 只允许 {sorted(_BUSINESS_ENV_KEYS)}"
        )
    # review-T-B02 F5：同一路径两种写法都给了且取值不同 → 启动失败
    # （否则 Settings.ingest_* 取扁平别名、business 取嵌套写法，两处不一致）。错误消息只含变量名。
    given = {
        name: upper[name].strip()
        for name in _BUSINESS_ENV_KEYS
        if upper.get(name) is not None and upper[name].strip() != ""
    }
    by_path: dict[tuple[str, ...], dict[str, str]] = {}
    for name, value in given.items():
        by_path.setdefault(_BUSINESS_ENV_KEYS[name], {})[name] = value
    conflicts = sorted(sorted(names) for names in by_path.values() if len(set(names.values())) > 1)
    if conflicts:
        raise ConfigError(f"业务配置环境变量取值冲突（同一键的两种写法取值不同）：{conflicts}")
    layer: dict[str, Any] = {}
    # 扁平别名先写、嵌套写法后写（两者取值相同时结果一样）
    for name in sorted(_BUSINESS_ENV_KEYS, key=lambda n: n.startswith("BUSINESS__")):
        raw = upper.get(name)
        if raw is None or raw.strip() == "":
            continue
        node = layer
        *parents, leaf = _BUSINESS_ENV_KEYS[name]
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = raw.strip()
    return layer


class YamlDirSettingsSource(PydanticBaseSettingsSource):
    """``business`` 字段的来源：``config/*.yaml`` 深合并环境变量白名单层（见 :func:`deep_merge`）。

    初始化参数里直接给 ``business`` 时以初始化参数为准（测试用），不经本来源。
    """

    def __init__(self, settings_cls: type[BaseSettings], config_dir: Path) -> None:
        super().__init__(settings_cls)
        self._config_dir = config_dir

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        if field_name == "business":
            return self()["business"], field_name, True
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        found = load_yaml_dir(self._config_dir)
        check_config_dir_files(found, self._config_dir)
        return {"business": deep_merge(found, business_env_layer())}


class SealPublicKeysSource(PydanticBaseSettingsSource):
    """``data_licence_seal_public_keys`` 的文件来源：``$SECRETS_DIR``（默认 ``/run/secrets``）
    下的同名文件（运维 T-O09 以 compose secret 挂载）。环境变量优先（在本来源之前）。
    只认这一个字段：    私钥不经 Settings（见 :mod:`app.licences.keys`）。"""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        try:
            text = read_secret(PUBLIC_KEYS_NAME)
        except SealKeyError as exc:
            raise ConfigError(str(exc)) from None
        return {PUBLIC_KEYS_NAME: text} if text else {}


def check_config_dir_files(found: dict[str, Any], config_dir: Path) -> None:
    """``config/`` 顶层只允许九个约定文件（缺失或多余都失败）。"""
    missing = sorted(set(BUSINESS_FILES) - set(found))
    extra = sorted(set(found) - set(BUSINESS_FILES))
    if missing or extra:
        raise ConfigError(
            f"config 目录 {config_dir} 文件不符合 plan §6.1："
            f"缺少 {missing or '无'}，多余 {extra or '无'}"
        )


#: Settings 顶层心跳字段 ↔ ``business.ingest.heartbeat`` 的键
_INGEST_FIELD_KEYS: Final = (
    ("ingest_heartbeat_key", "key"),
    ("ingest_paused_key", "paused_key"),
    ("ingest_stale_after_s", "stale_after_s"),
)


class _InitNoneIsUnset(PydanticBaseSettingsSource):
    """构造参数层：``business`` 里值为 ``None`` 的键视为未覆盖（plan §6.1 null 语义）。

    pydantic-settings 会把构造参数深合并到 YAML 之上，但 ``None`` 叶子会顶掉 YAML 的值；
    这里先剔除 ``None``，与 :func:`deep_merge` 口径一致。其他字段原样透传。
    """

    def __init__(self, settings_cls: type[BaseSettings], inner: PydanticBaseSettingsSource) -> None:
        super().__init__(settings_cls)
        self._inner = inner

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        data = dict(self._inner())
        business = data.get("business")
        if isinstance(business, Mapping):
            if hits := _sensitive_key_paths(business):
                raise ConfigError(
                    f"business 覆盖含疑似敏感键 {hits}：licence/密码/密钥只能走环境变量"
                )
            data["business"] = _strip_none(business)
        return data


class AuthAbusePolicy(BaseModel):
    """无验证码的防滥用阈值（plan §3.6，T-B03a）。

    默认值逐条取自 plan §3.6；plan §6.1 尚无对应 YAML 段与键名（待架构师定），先作为
    ``Settings.auth_abuse`` 的结构化字段（测试可整体覆盖），不新增环境变量。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: 登录：同一 IP 每分钟 ≤ 10 次
    login_ip_per_minute: int = Field(default=10, ge=1)
    #: 注册：同一 IP 每小时 ≤ 5 次、每日 ≤ 20 次
    register_ip_per_hour: int = Field(default=5, ge=1)
    register_ip_per_day: int = Field(default=20, ge=1)
    #: 全站 pending 账户数 ≥ 200 时暂停注册（503 REGISTRATION_CLOSED）
    pending_cap: int = Field(default=200, ge=1)
    #: 同一用户名连续失败 5 次锁定 15 分钟，再失败递增（30/60 分钟…），上限 24 小时
    lock_after_failures: int = Field(default=5, ge=1)
    lock_base_s: int = Field(default=900, ge=1)
    lock_max_s: int = Field(default=86_400, ge=1)

    @model_validator(mode="after")
    def _check(self) -> AuthAbusePolicy:
        if self.lock_base_s > self.lock_max_s:
            raise ValueError("lock_base_s 不能大于 lock_max_s")
        if self.register_ip_per_hour > self.register_ip_per_day:
            raise ValueError("register_ip_per_hour 不能大于 register_ip_per_day")
        return self


class Settings(BaseSettings):
    """后端 API 进程的配置。字段名大写即对应环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # --- 通用 ---
    app_env: AppEnv = "local"
    service_name: str = "api"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    #: 契约 §1 基础路径；nginx 以 ``proxy_pass http://api_upstream;``（不带 URI）原样转发
    #: ``/api/v1/...``，两者一致（运维 96c1c8e 修复 B1 后；review-T-B02 F6）。
    api_prefix: str = "/api/v1"

    # --- 依赖 ---
    database_url: SecretStr | None = None
    redis_url: str | None = None
    health_check_timeout_s: float = Field(default=1.0, gt=0, le=10)

    # --- ingest 新鲜度（/health/ready 的 ingest 字段，契约 §7.10）---
    # 未设置环境变量时取 ingest.yaml 的 heartbeat 段（见 _ingest_keys_from_yaml）；
    # 下面的默认值只在直接构造 Settings 且不经 yaml 来源时生效，与 plan §6.1 一致。
    ingest_heartbeat_key: str = Field(default="ingest:heartbeat", min_length=1)
    ingest_paused_key: str = Field(default="ingest:paused", min_length=1)
    ingest_stale_after_s: int = Field(default=120, gt=0)

    # --- 密钥 ---
    app_master_key: SecretStr | None = None
    #: T-B49：beat 排程“清理到期证书冷却记录”的间隔秒数（worker 执行
    #: ``purge_expired_cooldowns``）；环境变量 ``COOLDOWN_PURGE_INTERVAL_S``（beat 读取）。
    #: 默认 3600，最小 60（与原 cooldown-purge 服务的 ``AIA_COOLDOWN_PURGE_INTERVAL_S`` 一致）。
    cooldown_purge_interval_s: int = Field(default=3600, ge=60)
    #: 架构师裁定（T-live-83a031c §8 / T-A04 待写入契约）：beat 排程“清理 discarded/failed 批次残留
    #: 预览行”的间隔秒数（worker 执行 ``purge_uncommitted_import_rows``）；环境变量
    #: ``IMPORT_ROWS_PURGE_INTERVAL_S``，默认 3600（每小时），最小 60。
    import_rows_purge_interval_s: int = Field(default=3600, ge=60)
    #: 评审 bbf58a0 m6 / plan 7.3：beat 排程“删除 retained_until 已到期的原始导入文件”的间隔秒数
    #: （worker 执行 ``purge_expired_raw_files``）；环境变量 ``IMPORT_RAW_PURGE_INTERVAL_S``，
    #: 默认 86400（plan 7.3 每日清理），最小 60。
    import_raw_purge_interval_s: int = Field(default=86400, ge=60)
    #: ``IMPORT_STORAGE_PATH``（T-B46，plan §3.5A）：原始导入文件根目录（仓库外、加密存放）。
    #: 未设置时 local/test 用系统临时目录，其他环境上传返回 ``503 MAINTENANCE``。
    import_storage_path: Path | None = None
    #: ``MASTER_SNAPSHOT_PATH``（T-B52，plan 4.6.2）：证券主数据原始快照根目录
    #: （公开数据，保留 90 天）。
    #: 未设置时 local/test 用 ``<tmp>/aia-master``，其他环境同步任务失败（不落盘到镜像内）。
    master_snapshot_path: Path | None = None
    #: 证书封装公钥（T-A07 / T-O09）：单行 JSON ``{"<版本>": "<base64 SPKI DER>"}``；环境变量
    #: ``DATA_LICENCE_SEAL_PUBLIC_KEYS`` 或 ``/run/secrets/data_licence_seal_public_keys``。
    #: 未配置时 ``PUT /me/data-licence`` 返回 503（不落明文）。api **没有**私钥。
    data_licence_seal_public_keys: str | None = None
    #: 新封装使用的公钥版本（``DATA_LICENCE_SEAL_KEY_VERSION``）
    data_licence_seal_key_version: int | None = Field(default=None, ge=1)
    #: ``DATA_LICENCE_SETTINGS_ENABLED``（review M4 / T-B03d）：证书设置入口（PUT / PATCH / test）
    #: 是否开放。未设置时 production 关闭、其余环境开启；ingest 每证书调度（T-B04a-x）完成前
    #: 生产不要打开。见 :attr:`licence_settings_enabled`。
    data_licence_settings_enabled: bool | None = None
    #: T-B127 / 契约 daily-bars-source §7：日 K 来源。默认 off；fake 仅 APP_ENV=test。
    #: 环境变量 ``DAILY_BARS_SOURCE``。mairui 在单 C 完成前为惰性（不拉、不写、不建连）。
    daily_bars_source: Literal["off", "fake", "mairui"] = "off"

    # 认证（plan §3.6 / 契约 §1.3，T-B03）：注册模式与会话 Cookie 的 Secure 标记
    #: ``REGISTRATION_MODE``：closed（默认，``/auth/register`` → 503）/ invite / open
    registration_mode: RegistrationMode = RegistrationMode.CLOSED
    #: ``SESSION_COOKIE_SECURE``：生产必须 true；只有 APP_ENV=local/test 可设 false（S6）
    session_cookie_secure: bool = True
    #: 防滥用阈值（T-B03a，plan §3.6）
    auth_abuse: AuthAbusePolicy = Field(default_factory=AuthAbusePolicy)
    #: ``TRUSTED_PROXIES``：只有直连对端落在这些网段（我方 nginx）时才采信转发头，且只取
    #: ``X-Forwarded-For`` 最右一跳（nginx 追加的 ``$remote_addr``）。JSON 数组；空 = 不采信。
    trusted_proxies: tuple[str, ...] = _DEFAULT_TRUSTED_PROXIES
    #: ``SITE_ORIGINS``（契约 §1.3 #30 ④，plan 第 9 节问题 84）：本站源
    #: （``scheme://host[:port]``），JSON 数组。``/auth/login``、``/auth/register`` 带 ``Origin``
    #: 头且不在其中 → ``403 CSRF_FAILED``。为空时退回同源判定：``Origin`` 的 host[:port]
    #: 必须等于请求的 ``Host`` 头（nginx 透传 ``$host``）。
    site_origins: tuple[str, ...] = ()

    # --- 分页（契约 §1.2） ---
    page_limit_default: int = Field(default=50, ge=1)
    page_limit_max: int = Field(default=200, ge=1, le=200)  # = pagination.PAGE_LIMIT_MAX
    cursor_ttl_s: int = Field(default=86_400, gt=0)

    # --- 业务配置（config/*.yaml，只读） ---
    config_dir: Path = Field(default_factory=_default_config_dir)
    business: BusinessConfig

    @model_validator(mode="before")
    @classmethod
    def _ingest_keys_from_yaml(cls, data: object) -> object:
        """环境变量没给时，用 ingest.yaml ``heartbeat`` 段填充三个心跳参数。"""
        if not isinstance(data, dict):
            return data
        business = data.get("business")
        heartbeat: Any = None
        if isinstance(business, BusinessConfig):
            heartbeat = business.ingest.heartbeat.model_dump()
        elif isinstance(business, dict):
            ingest = business.get("ingest")
            if isinstance(ingest, dict):
                heartbeat = ingest.get("heartbeat")
        if isinstance(heartbeat, dict):
            for field, key in _INGEST_FIELD_KEYS:
                if data.get(field) is None and key in heartbeat:
                    data = {**data, field: heartbeat[key]}
        return data

    @field_validator("api_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        value = value.strip()
        if value in ("", "/"):
            return ""
        if not value.startswith("/"):
            value = "/" + value
        return value.rstrip("/")

    @field_validator("trusted_proxies")
    @classmethod
    def _check_proxies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for net in value:
            ipaddress.ip_network(net, strict=False)  # 非法网段 → ValueError → 启动失败
        return value

    @field_validator("site_origins")
    @classmethod
    def _check_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for raw in value:
            o = raw.strip().rstrip("/").lower()
            parts = urlsplit(o)
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path:
                raise ValueError("SITE_ORIGINS 每项须为 scheme://host[:port]（不带路径）")
            out.append(o)
        return tuple(out)

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.page_limit_default > self.page_limit_max:
            raise ValueError("page_limit_default 不能大于 page_limit_max")
        # T-B49：主密钥只对 api / worker 强制；白名单外的 SERVICE_NAME 在非 local/test 拒绝启动；
        # ingest 持有主密钥 → 任何环境都拒绝启动（ingest 不应能派生任何 HMAC / 签名密钥）
        if self.app_env not in _DEV_ENVS and self.service_name not in SERVICE_NAMES:
            raise ValueError(
                f"SERVICE_NAME={self.service_name!r} 不在白名单 {sorted(SERVICE_NAMES)} 内"
            )
        if (
            self.app_env not in _DEV_ENVS
            and self.service_name in MASTER_KEY_SERVICES
            and self.app_master_key is None
        ):
            raise ValueError(
                f"APP_MASTER_KEY 在非 local/test 环境必须设置（SERVICE_NAME={self.service_name}）"
            )
        if self.service_name in MASTER_KEY_FORBIDDEN_SERVICES and self.app_master_key is not None:
            raise ValueError(f"SERVICE_NAME={self.service_name} 不得持有 APP_MASTER_KEY，拒绝启动")
        if self.app_master_key is not None and len(self.app_master_key.get_secret_value()) < 32:
            raise ValueError("APP_MASTER_KEY 至少 32 个字符")
        if self.data_licence_seal_public_keys:
            try:
                keys = parse_public_keys(self.data_licence_seal_public_keys)
            except SealKeyError as exc:
                raise ValueError(str(exc)) from None
            if self.data_licence_seal_key_version is None:
                raise ValueError(
                    "配置了 DATA_LICENCE_SEAL_PUBLIC_KEYS 时必须设置 DATA_LICENCE_SEAL_KEY_VERSION"
                )
            if self.data_licence_seal_key_version not in keys:
                raise ValueError("DATA_LICENCE_SEAL_KEY_VERSION 在封装公钥里不存在")
        # review-T-B03 S6 / T-A05：只有 local/test 允许关闭 Cookie 的 Secure 标记
        if not self.session_cookie_secure and self.app_env not in _DEV_ENVS:
            raise ValueError("SESSION_COOKIE_SECURE=false 只允许在 APP_ENV=local/test 使用")
        if self.daily_bars_source == "fake" and self.app_env != "test":
            raise ValueError("DAILY_BARS_SOURCE=fake 只允许在 APP_ENV=test 使用")
        return self

    @property
    def licence_settings_enabled(self) -> bool:
        if self.data_licence_settings_enabled is not None:
            return self.data_licence_settings_enabled
        return self.app_env != "production"

    def with_business_overrides(self, runtime: Mapping[str, Any] | None) -> Settings:
        """叠加管理端运行时覆盖层（存数据库），返回新的 :class:`Settings`；本对象不变。

        优先级：环境变量白名单 > ``runtime`` > 当前 business（YAML）。合并后整体严格校验，
        不合法抛 :class:`ConfigError`（消息不含取值）。“只限可热调的键”的白名单由各管理端
        接口负责（T-B 后续任务），这里只做结构合法性与敏感键检查。
        """
        if not runtime:
            return self
        if hits := _sensitive_key_paths(runtime):
            raise ConfigError(f"运行时覆盖含疑似敏感键 {hits}：licence/密码/密钥只能走环境变量")
        merged = deep_merge(self.business.model_dump(), runtime, business_env_layer())
        try:
            business = BusinessConfig.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError(f"运行时覆盖校验失败：{_describe(exc, 'business')}") from None
        # F5：ingest_* 三个字段原本取自 business.ingest.heartbeat 的，跟着新 business 刷新；
        # 构造时显式给了不同值的（测试用）保持不变。
        old_hb, new_hb = self.business.ingest.heartbeat, business.ingest.heartbeat
        update: dict[str, Any] = {"business": business}
        for field, key in _INGEST_FIELD_KEYS:
            if getattr(self, field) == getattr(old_hb, key):
                update[field] = getattr(new_hb, key)
        return self.model_copy(update=update)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        raw_dir = os.environ.get("CONFIG_DIR")
        config_dir = Path(raw_dir) if raw_dir else _default_config_dir()
        # 不启用 dotenv：.env 只用于 compose 变量插值，不整体注入进程（T-O01 约定）
        return (
            _InitNoneIsUnset(settings_cls, init_settings),
            env_settings,
            SealPublicKeysSource(settings_cls),
            YamlDirSettingsSource(settings_cls, config_dir),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级单例；测试中可 ``get_settings.cache_clear()`` 或用 ``create_app(settings)``。

    配置不合法时抛 :class:`ConfigError`（消息里只有字段路径与错误说明，不回显取值，
    以免环境变量中的密钥进入日志），进程因此启动失败。
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(f"配置校验失败：{_describe(exc)}") from None


def _describe(exc: ValidationError, prefix: str = "") -> str:
    """校验错误 → “字段路径: 说明; …”，不回显取值。"""
    problems = []
    for err in exc.errors(include_input=False, include_url=False):
        parts = [prefix] if prefix else []
        parts += [str(p) for p in err["loc"]]
        problems.append(f"{'.'.join(parts) or '<root>'}: {err['msg']}")
    return "; ".join(problems)
