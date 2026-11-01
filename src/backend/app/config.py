"""应用配置（plan.md §6、§8 T-B01）：环境变量 + ``config/*.yaml``。

- 运行参数（数据库、Redis、密钥、端口等）只来自环境变量，与
  ``deploy/compose/docker-compose.yml`` 中 ``api`` 服务的 ``environment`` 同名。
- 业务配置（``config/realtime.yaml``、``ingest.yaml`` 等）只读加载到
  :attr:`Settings.business`，键为文件名（不含扩展名）。``config/strategies/`` 子目录
  不在这里加载：L2 模板要经导入器成为不可变 DB 版本，放文件不会激活（plan §2.5.13）。
- 本服务**不读取** ``MAIRUI_LICENCE``：licence 只注入 ``ingest`` 容器（plan §2.1A）；
  未声明的环境变量一律忽略（``extra="ignore"``）。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"配置文件解析失败：{path.name}") from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件顶层必须是映射：{path.name}")
        result[path.stem] = data
    return result


class YamlDirSettingsSource(PydanticBaseSettingsSource):
    """把 ``config/*.yaml`` 作为 ``business`` 字段的来源（优先级低于环境变量与初始化参数）。"""

    def __init__(self, settings_cls: type[BaseSettings], config_dir: Path) -> None:
        super().__init__(settings_cls)
        self._config_dir = config_dir

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        if field_name == "business":
            return load_yaml_dir(self._config_dir), field_name, True
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return {"business": load_yaml_dir(self._config_dir)}


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

    # --- ingest 新鲜度（/health 的 ingest 字段；键名为临时约定，待 T-B04a 对齐） ---
    ingest_heartbeat_key: str = "ingest:heartbeat"
    ingest_paused_key: str = "ingest:paused"
    ingest_stale_after_s: int = Field(default=120, gt=0)

    # --- 密钥 ---
    app_master_key: SecretStr | None = None

    # --- 分页（契约 §1.2） ---
    page_limit_default: int = Field(default=50, ge=1)
    page_limit_max: int = Field(default=200, ge=1)
    cursor_ttl_s: int = Field(default=86_400, gt=0)

    # --- 业务配置（config/*.yaml，只读） ---
    config_dir: Path = Field(default_factory=_default_config_dir)
    business: dict[str, Any] = Field(default_factory=dict)

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
    """进程级单例；测试中可 ``get_settings.cache_clear()`` 或用 ``create_app(settings)``。"""
    return Settings()
