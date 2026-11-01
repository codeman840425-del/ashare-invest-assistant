"""应用配置（plan.md §6、§8 T-B01）：环境变量 + ``config/*.yaml``。

- 运行参数（数据库、Redis、密钥、端口等）只来自环境变量，与
  ``deploy/compose/docker-compose.yml`` 中 ``api`` 服务的 ``environment`` 同名。
- 业务配置（``config/realtime.yaml``、``ingest.yaml`` 等五个文件，plan §6.1）只读加载到
  :attr:`Settings.business`，并按 :mod:`app.config_files` 严格校验：未知键、缺文件、
  多余文件、取值越界 → 启动失败。``config/strategies/`` 子目录不在这里加载：L2 模板要经
  导入器成为不可变 DB 版本，放文件不会激活（plan §2.5.13）。
- 三层优先级与合并口径（plan §6.1，T-A02）：环境变量（只限白名单键）> 管理端运行时覆盖
  （:meth:`Settings.with_business_overrides`）> YAML。三层按 :func:`deep_merge` **深合并**：
  映射逐键递归，列表与标量整体替换，``null`` 视为未覆盖；合并结果再整体走严格校验
  （``extra="forbid"`` + ``schema_version``），未知键出现在任何一层都失败。
- 环境变量白名单（plan §6.1 注明的键）：``INGEST_HEARTBEAT_KEY`` / ``INGEST_PAUSED_KEY`` /
  ``INGEST_STALE_AFTER_S``，以及等价的嵌套写法 ``BUSINESS__INGEST__HEARTBEAT__KEY`` /
  ``…__PAUSED_KEY`` / ``…__STALE_AFTER_S``（分隔符 ``__``）。其他 ``BUSINESS__*`` 或整块
  ``BUSINESS`` 环境变量 → 启动失败（见 :func:`business_env_layer`）。
- 本服务**不读取** ``MAIRUI_LICENCE``：licence 只注入 ``ingest`` 容器（plan §2.1A）；
  未声明的环境变量一律忽略（``extra="ignore"``）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.config_files import BUSINESS_FILES, BusinessConfig

AppEnv = Literal["local", "test", "staging", "production"]

#: 允许在缺少 APP_MASTER_KEY 时用进程内临时密钥的环境（游标签名重启即失效）
_DEV_ENVS: frozenset[str] = frozenset({"local", "test"})


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


#: plan §6.1 / §7.4A：licence、密码、密钥只走环境变量；YAML 中出现这类键名直接启动失败（评审 m2）
_SENSITIVE_KEY_PARTS: Final = frozenset(
    {"licence", "license", "password", "passwd", "secret", "token", "apikey", "credential"}
)


def _sensitive_key_paths(data: object, path: str = "") -> list[str]:
    """递归找出键名分段（按 ``_`` / ``-`` / ``.`` 切分）命中敏感词的键路径；只返回路径，不含值。"""
    hits: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            k = str(key)
            here = f"{path}.{k}" if path else k
            parts = set(re.split(r"[_\-.]", k.lower()))
            if parts & _SENSITIVE_KEY_PARTS or "api_key" in k.lower():
                hits.append(here)
            hits.extend(_sensitive_key_paths(value, here))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            hits.extend(_sensitive_key_paths(item, f"{path}[{i}]"))
    return hits


def load_yaml_dir(config_dir: Path) -> dict[str, Any]:
    """读取 ``config_dir`` 下一层的 ``*.yaml`` / ``*.yml``（不递归），按文件名排序。

    每个文件顶层必须是映射（或空文件），返回 ``{文件名stem: 内容}``。
    目录不存在时返回空字典（Phase 0 仓库里只有 ``config/strategies/``）。
    """
    if not config_dir.is_dir():
        return {}
    result: dict[str, Any] = {}
    files = sorted(p for p in config_dir.iterdir() if p.is_file() and p.suffix in {".yaml", ".yml"})
    for path in files:
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
        if hits := _sensitive_key_paths(data):
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
    空字符串视为未设置。同一路径同时给了嵌套写法与扁平别名时，嵌套写法优先。
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
    layer: dict[str, Any] = {}
    # 扁平别名先写、嵌套写法后写 → 嵌套写法优先
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


def check_config_dir_files(found: dict[str, Any], config_dir: Path) -> None:
    """``config/`` 顶层只允许五个约定文件（缺失或多余都失败）。"""
    missing = sorted(set(BUSINESS_FILES) - set(found))
    extra = sorted(set(found) - set(BUSINESS_FILES))
    if missing or extra:
        raise ConfigError(
            f"config 目录 {config_dir} 文件不符合 plan §6.1："
            f"缺少 {missing or '无'}，多余 {extra or '无'}"
        )


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
    #: 契约 §1 基础路径。注意：T-O01 的 nginx 以 ``proxy_pass http://api_upstream/;`` 反代
    #: ``/api/``，会去掉 ``/api`` 前缀；两者对齐前可用环境变量覆盖（见 reports/T-B01.md）。
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

    # --- 分页（契约 §1.2） ---
    page_limit_default: int = Field(default=50, ge=1)
    page_limit_max: int = Field(default=200, ge=1)
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
            pairs = (
                ("ingest_heartbeat_key", "key"),
                ("ingest_paused_key", "paused_key"),
                ("ingest_stale_after_s", "stale_after_s"),
            )
            for field, key in pairs:
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

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.page_limit_default > self.page_limit_max:
            raise ValueError("page_limit_default 不能大于 page_limit_max")
        if self.app_env not in _DEV_ENVS and self.app_master_key is None:
            raise ValueError("APP_MASTER_KEY 在非 local/test 环境必须设置")
        if self.app_master_key is not None and len(self.app_master_key.get_secret_value()) < 32:
            raise ValueError("APP_MASTER_KEY 至少 32 个字符")
        return self

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
        return self.model_copy(update={"business": business})

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
            init_settings,
            env_settings,
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
