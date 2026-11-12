# ruff: noqa: S101
"""O-CI1-REFREG: business/reference loading and unchanged public consumers, offline."""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import ConfigError, Settings, check_config_dir_files, load_yaml_dir
from app.config_files import BUSINESS_FILES, BusinessConfig, ShareClassListConfig
from app.financial_basis import load_share_classes, share_class_at
from app.reference_files import REFERENCE_FILES, load_reference_file

CONFIG = Path(__file__).resolve().parents[3] / "config"
BUSINESS_NAMES = {
    "realtime",
    "ingest",
    "market_rules",
    "risk_controls",
    "horizon_classifier",
    "llm",
    "imports",
    "auth",
    "securities",
}


def _reference() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "list_version": 2,
        "as_of": "2026-11-01",
        "sources": {"note": "synthetic interval only", "union_complete": True},
        "records": [
            {
                "code": "600000.SH",
                "class": "H",
                "paired_code": "00001",
                "paired_market": "HK",
                "effective_from": "2025-01-02",
                "effective_to": "2025-12-31",
                "source": "synthetic",
                "verified": False,
            }
        ],
    }


def _write(directory: Path, data: dict[str, Any]) -> None:
    (directory / "share_class_list.yaml").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in BUSINESS_NAMES:
        shutil.copyfile(CONFIG / f"{name}.yaml", directory / f"{name}.yaml")
    secrets_dir = tmp_path / "empty-secrets"
    secrets_dir.mkdir()
    for name in list(os.environ):
        if name.startswith("BUSINESS") or name in {
            "APP_MASTER_KEY",
            "MAIRUI_LICENCE",
            "DATA_LICENCE_SEAL_PUBLIC_KEYS",
            "DATA_LICENCE_SEAL_KEY_VERSION",
            "INGEST_HEARTBEAT_KEY",
            "INGEST_PAUSED_KEY",
            "INGEST_STALE_AFTER_S",
        }:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CONFIG_DIR", str(directory))
    monkeypatch.setenv("SECRETS_DIR", str(secrets_dir))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SERVICE_NAME", "api")
    _write(directory, _reference())
    return directory


def test_refreg_business_registry_and_startup_keep_nine_files(runtime_dir: Path) -> None:
    assert set(BUSINESS_FILES) == BUSINESS_NAMES
    assert set(BusinessConfig.model_fields) == BUSINESS_NAMES
    assert REFERENCE_FILES["share_class_list.yaml"] is ShareClassListConfig
    found = load_yaml_dir(runtime_dir)
    check_config_dir_files(found, runtime_dir)
    settings = Settings(database_url=None, redis_url=None)
    assert set(found) == BUSINESS_NAMES
    assert settings.business.model_dump() == BusinessConfig.model_validate(found).model_dump()
    assert "share_class_list" not in settings.business.model_dump()
    reference = load_reference_file(runtime_dir, "share_class_list.yaml")
    assert isinstance(reference, ShareClassListConfig)
    assert reference.model_dump() == _reference()


def test_refreg_checked_in_reference_and_existing_consumers_agree() -> None:
    reference = load_reference_file(CONFIG, "share_class_list.yaml")
    direct = load_share_classes(CONFIG / "share_class_list.yaml")
    assert reference.model_dump() == direct
    assert set(load_yaml_dir(CONFIG)) == BUSINESS_NAMES
    for day in ("2025-01-01", "2025-01-02", "2025-12-31"):
        assert share_class_at(reference.model_dump(), "600000.SH", day) == share_class_at(
            direct, "600000.SH", day
        )


@pytest.mark.parametrize(
    ("day", "member"), [("2025-01-01", None), ("2025-01-02", "A+H"), ("2025-12-31", None)]
)
def test_refreg_same_record_version_and_interval_consumer(
    runtime_dir: Path, day: str, member: str | None
) -> None:
    reference = load_reference_file(runtime_dir, "share_class_list.yaml")
    data = reference.model_dump()
    result = share_class_at(data, "600000.SH", day)
    assert result == share_class_at(
        load_share_classes(runtime_dir / "share_class_list.yaml"), "600000.SH", day
    )
    assert result["member"] == member
    assert result["share_class_list_version"] == 2
    assert result["share_class_check"] == "list"
    assert data["records"][0]["verified"] is False


@pytest.mark.parametrize(
    "case",
    [
        "schema",
        "missing_header",
        "unknown_header",
        "version",
        "as_of",
        "sources",
        "record_extra",
        "verified_type",
        "missing_date",
        "bad_interval",
        "paired_market",
        "duplicate",
    ],
)
def test_refreg_invalid_reference_still_rejected_on_load_and_startup(
    runtime_dir: Path, case: str
) -> None:
    data = copy.deepcopy(_reference())
    row = data["records"][0]
    if case == "schema":
        data["schema_version"] = 2
    elif case == "missing_header":
        del data["as_of"]
    elif case == "unknown_header":
        data["unexpected"] = True
    elif case == "version":
        data["list_version"] = 0
    elif case == "as_of":
        data["as_of"] = "invalid-date"
    elif case == "sources":
        data["sources"] = []
    elif case == "record_extra":
        row["unexpected"] = True
    elif case == "verified_type":
        row["verified"] = "false"
    elif case == "missing_date":
        row["effective_from"] = None
    elif case == "bad_interval":
        row["effective_to"] = row["effective_from"]
    elif case == "paired_market":
        row["paired_market"] = "SH"
    elif case == "duplicate":
        data["records"].append(copy.deepcopy(row))
    else:
        raise AssertionError(case)
    _write(runtime_dir, data)
    with pytest.raises(ValidationError):
        load_reference_file(runtime_dir, "share_class_list.yaml")
    with pytest.raises(ValidationError):
        Settings(database_url=None, redis_url=None)


def test_refreg_reference_sensitive_keys_remain_blocked_before_model_validation(
    runtime_dir: Path,
) -> None:
    data = _reference()
    data["sources"]["password"] = 9182736
    _write(runtime_dir, data)
    with pytest.raises(ConfigError, match="疑似敏感键") as denied:
        load_yaml_dir(runtime_dir)
    assert "9182736" not in str(denied.value)


def test_refreg_reference_cannot_be_injected_as_business_override(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(database_url=None, redis_url=None)
    with pytest.raises(ConfigError, match="share_class_list"):
        settings.with_business_overrides({"share_class_list": _reference()})
    monkeypatch.setenv("BUSINESS__SHARE_CLASS_LIST__LIST_VERSION", "3")
    with pytest.raises(ConfigError, match="不允许的业务配置环境变量"):
        Settings(database_url=None, redis_url=None)


def test_refreg_missing_reference_stays_explicit_at_consumer(runtime_dir: Path) -> None:
    reference_path = runtime_dir / "share_class_list.yaml"
    reference_path.unlink()
    assert set(Settings(database_url=None, redis_url=None).business.model_dump()) == BUSINESS_NAMES
    with pytest.raises(FileNotFoundError):
        load_reference_file(runtime_dir, "share_class_list.yaml")
    with pytest.raises(FileNotFoundError):
        load_share_classes(reference_path)
