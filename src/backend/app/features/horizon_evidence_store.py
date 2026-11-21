"""T-A202 §3：追加登记显式材料；事务提交及发布由调用方负责。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from app.db.tables.horizon import horizon_completion_evidence as completions
from app.db.tables.horizon import horizon_input_versions as versions


class EvidenceRejected(ValueError):  # noqa: N818 - 契约异常名
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class EvidenceConflict(EvidenceRejected):
    pass


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        if obj.utcoffset() is None:
            raise EvidenceRejected("timezone_required")
        return obj.astimezone(UTC).isoformat()
    if isinstance(obj, (UUID, date)):
        return str(obj)
    raise EvidenceRejected("invalid_json_type")


def _canon(obj: object) -> str:
    return json.dumps(
        obj,
        default=_json_default,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def canon_sha256(obj: object) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


# §3.1 出处表；源名约定与 scope 搭配未验证，vendor_factor 出处未验证，拒绝登记。
SOURCES = {
    "calendar": {"merged_calendar", "fake"},
    "daily_bar": {"mairui", "fake"},
    "ex_rights": {"tdx_gbbq", "fake"},
    "adjust_factor": {"derived"},
    "feature": {"derived"},
}


def validate_origin(kind: str, source: str, scope: str) -> None:
    scopes = {"fake": {"synthetic"}, "mairui": {"per_licence"}}
    if source not in SOURCES.get(kind, set()) or scope not in scopes.get(
        source, {"public", "per_licence"}
    ):
        raise EvidenceRejected("kind_source_scope")


# §3.4 六个证据槽只验证非空对象；内部结构未验证，raw_units 映射值可为 null。
# coverage/trade_dates/issues、proof.sha256：契约为建议必填，未验证；按必填处理。
SCHEMAS = {
    "calendar": (
        "is_open:bool coverage_start:date coverage_end:date source_version:str "
        "sha256:sha overlap_check:object"
    ),
    "daily_bar": (
        "open:decimal? high:decimal? low:decimal? close:decimal? pre_close:decimal? "
        "volume:decimal? amount:decimal? is_suspended:bool? raw_fields:object "
        "raw_units:object price_unit:str? volume_unit:str? amount_unit:str? code:str "
        "trade_date:date adj_type:str source:str? source_licence_id:uuid? "
        "fetched_at:time? hash:str"
    ),
    "ex_rights": (
        "code:str ex_date:date cash_per_share:decimal rights_price:decimal "
        "bonus_ratio:decimal rights_ratio:decimal snapshot_sha256:sha "
        "source_version:str version_hash:sha"
    ),
    "adjust_factor": (
        "date:date value:positive snapshot_sha256:sha transform_version:str "
        "algo_audit:object coverage_start:date coverage_end:date trade_dates:date[] "
        "issues:str[] integrity_audit:object"
    ),
    "feature": (
        "values:object units:object raw_values:object transforms:object window:window "
        "qfq_anchor:date as_of:time d:date? dependency_ids:uuid[+] evidence_ids:uuid[+] "
        "feature_set_version:str"
    ),
    "proof": (
        "code:str trade_date:date source:str licence_id:uuid? user_id:uuid "
        "version_hash:sha source_version:str sha256:sha"
    ),
    "batch": (
        "run_id:uuid owner_id:uuid? licence_id:uuid? members:members status:str "
        "finished_at:time available_at:time issues:str[] kind:str step:str "
        "run_date:date"
    ),
}


def _valid(value: object, spec: str) -> bool:
    if spec.endswith("?"):
        return value is None or _valid(value, spec[:-1])
    if spec.endswith(("[]", "[+]")):
        base = spec.split("[")[0]
        return (
            isinstance(value, list)
            and (bool(value) or spec.endswith("[]"))
            and all(_valid(v, base) for v in value)
        )
    if spec == "bool":
        return type(value) is bool
    if spec == "object":
        return isinstance(value, dict) and bool(value)
    if spec == "members":
        return isinstance(value, list) and all(
            isinstance(v, list) and len(v) == 2 and _valid(v[0], "uuid") and _valid(v[1], "str")
            for v in value
        )
    if spec == "window":
        return isinstance(value, list) and len(value) == 2 and all(_valid(v, "date") for v in value)
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        if spec == "date":
            return date.fromisoformat(value).isoformat() == value
        if spec == "time":
            return datetime.fromisoformat(value).utcoffset() is not None
        if spec == "uuid":
            UUID(value)
        if spec == "sha":
            return re.fullmatch("[0-9a-f]{64}", value) is not None
        if spec in {"decimal", "positive"}:
            number = Decimal(value)
            return number.is_finite() and (spec == "decimal" or number > 0)
    except (ValueError, InvalidOperation):
        return False
    return True


def _fields(name: str, obj: object) -> None:
    if not isinstance(obj, dict):
        raise EvidenceRejected(f"{name}:object_required")
    for field in SCHEMAS[name].split():
        key, spec = field.split(":")
        if key not in obj or not _valid(obj[key], spec):
            raise EvidenceRejected(f"{name}:{key}")


def _receipt(obj: dict[str, Any], available_at: datetime | None) -> None:
    if available_at is not None and not _valid(obj.get("persisted_receipt"), "str"):
        raise EvidenceRejected("persisted_receipt_required")


def validate_payload(
    kind: str,
    payload: dict[str, Any],
    *,
    dependency_ids: Sequence[UUID],
    transform_version: str,
    available_at: datetime | None,
) -> None:
    if kind not in SOURCES:
        raise EvidenceRejected("kind")
    _fields(kind, payload)
    _receipt(payload, available_at)
    for key, expected in (
        ("dependency_ids", [str(v) for v in dependency_ids]),
        ("transform_version", transform_version),
    ):
        if key in payload and payload[key] != expected:
            raise EvidenceRejected(f"payload_outer_mismatch:{key}")
    for key, spec in (("snapshot_id", "uuid"), ("hash", "str")):
        if kind == "feature" and key in payload and not _valid(payload[key], spec):
            raise EvidenceRejected(f"feature:{key}")
    if kind == "feature" and ("snapshot_id" in payload) != ("hash" in payload):
        raise EvidenceRejected("feature:snapshot_binding")


def validate_batch(batch: dict[str, Any]) -> None:
    _fields("batch", batch)
    if (
        batch["status"] not in {"running", "ok", "partial", "failed", "skipped"}
        or batch["kind"] != "daily_batch"
        or batch["step"] != "daily_bars.fetch"
        or batch.get("window_trading_days") is not None
    ):
        raise EvidenceRejected("batch:routine_fields")


def validate_proof(
    proof: dict[str, Any], *, available_at: datetime | None, is_final: bool | None, proof_kind: str
) -> None:
    _fields("proof", proof)
    if is_final is not None and type(is_final) is not bool:
        raise EvidenceRejected("is_final_type")
    if available_at is not None:
        _json_default(available_at)
    _receipt(proof, available_at)
    # 真实同源完成声明及可核回执来源未验证；这里只检查显式非空材料，不发明厂商字段。
    if (
        is_final is True
        and proof_kind == "source_final_receipt"
        and not _valid(proof.get("source_final_receipt"), "str")
    ):
        raise EvidenceRejected("source_final_receipt_required")


def _row(conn: Connection, table: Table, row_id: UUID) -> Mapping[str, Any]:
    row = conn.execute(select(table).where(table.c.id == row_id)).mappings().first()
    if row is None:
        raise EvidenceRejected(f"missing:{table.name}")
    return dict(row)


def _in_scope(row: Mapping[str, Any], user_id: UUID, licence_id: UUID | None) -> bool:
    return row["user_id"] == user_id and (
        row["scope"] in {"public", "synthetic"} or row["licence_id"] == licence_id
    )


def _save(conn: Connection, table: Table, values: dict[str, Any], keys: Sequence[str]) -> UUID:
    try:
        with conn.begin_nested():
            new = conn.scalar(
                insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[table.c[k] for k in keys])
                .returning(table.c.id)
            )
    except DBAPIError as exc:
        diag = getattr(exc.orig, "diag", None)
        raise EvidenceRejected(
            f"database_constraint:{getattr(diag, 'message_primary', 'rejected')}"
        ) from exc
    if new is not None:
        return UUID(str(new))
    matches = [table.c[k].is_not_distinct_from(values[k]) for k in keys]
    old = conn.execute(select(table).where(*matches)).mappings().one()
    content = {k: v for k, v in values.items() if k != "id"}
    if _canon({k: old[k] for k in content}) != _canon(content):
        raise EvidenceConflict("idempotency_content_conflict")
    return UUID(str(old["id"]))


def register_version(
    conn: Connection,
    *,
    user_id: UUID,
    licence_id: UUID | None,
    kind: str,
    source: str,
    scope: str,
    code: str | None,
    data_date: date,
    source_key: str,
    source_version: str,
    payload: dict[str, Any],
    first_seen_at: datetime | None,
    available_at: datetime | None,
    computed_at: datetime | None,
    dependency_ids: Sequence[UUID],
    transform_version: str,
    supersedes_id: UUID | None = None,
) -> UUID:
    values = dict(locals())
    del values["conn"]
    validate_origin(kind, source, scope)
    for field in ("source_key", "source_version", "transform_version"):
        if not _valid(values[field], "str"):
            raise EvidenceRejected(f"version:{field}")
    for timestamp in (first_seen_at, available_at, computed_at):
        if timestamp is not None:
            _json_default(timestamp)
    version_id = uuid4()
    deps = list(dependency_ids)
    if version_id in deps or len(set(deps)) != len(deps):
        raise EvidenceRejected("dependency_self_or_duplicate")
    dependencies = [_row(conn, versions, dep) for dep in deps]
    if any(not _in_scope(row, user_id, licence_id) for row in dependencies):
        raise EvidenceRejected("dependency_scope")
    validate_payload(
        kind,
        payload,
        dependency_ids=deps,
        transform_version=transform_version,
        available_at=available_at,
    )
    if kind == "daily_bar":
        binding = {
            "code": code,
            "trade_date": str(data_date),
            "source": source,
            "source_licence_id": str(licence_id) if licence_id else None,
            "adj_type": "none",
        }
        for key, expected in binding.items():
            if payload[key] != expected:
                raise EvidenceRejected(f"payload_outer_mismatch:{key}")
    if kind == "adjust_factor":
        # 参考价=daily_bar 版本：未验证。
        for required in ("ex_rights", "daily_bar"):
            if not any(row["kind"] == required for row in dependencies):
                raise EvidenceRejected(f"dependency_required:{required}")
    evidence_rows = [_row(conn, completions, UUID(e)) for e in payload.get("evidence_ids", [])]
    for evidence in evidence_rows:
        if not _in_scope(_row(conn, versions, evidence["bar_version_id"]), user_id, licence_id):
            raise EvidenceRejected("evidence_scope")
        if kind == "feature" and evidence["bar_version_id"] not in deps:
            raise EvidenceRejected("evidence_bar_dependency")
    if kind in {"adjust_factor", "feature"}:
        if computed_at is None:
            raise EvidenceRejected("computed_at_required")
        visible = [row["available_at"] for row in [*dependencies, *evidence_rows]]
        derived_at = None if None in visible else max([computed_at, *visible])
        if available_at is not None and available_at != derived_at:
            raise EvidenceRejected("derived_available_at_mismatch")
        available_at = derived_at
        _receipt(payload, available_at)
    logical_key = ("user_id", "licence_id", "kind", "source", "code", "data_date", "source_key")
    identity = {key: values[key] for key in logical_key}
    if supersedes_id is not None:
        previous = _row(conn, versions, supersedes_id)
        if any(previous[k] != v for k, v in identity.items()):
            raise EvidenceRejected("supersedes_logical_key")
    values.update(available_at=available_at, dependency_ids=deps)
    version_hash = canon_sha256(values)
    return _save(
        conn,
        versions,
        dict(values, id=version_id, version_hash=version_hash),
        [*identity, "version_hash"],
    )


def register_completion(
    conn: Connection,
    *,
    bar_version_id: UUID,
    pipeline_run_id: UUID | None = None,
    is_final: bool | None,
    available_at: datetime | None,
    proof_kind: str,
    proof: dict[str, Any],
) -> UUID:
    validate_proof(proof, available_at=available_at, is_final=is_final, proof_kind=proof_kind)
    bar = _row(conn, versions, bar_version_id)
    binding_keys = "code trade_date source licence_id user_id version_hash source_version"
    for key in binding_keys.split():
        expected = bar["data_date" if key == "trade_date" else key]
        if proof[key] != (str(expected) if isinstance(expected, (UUID, date)) else expected):
            raise EvidenceRejected(f"proof_bar_mismatch:{key}")
    batches = proof.get("batches", [])
    if "batches" in proof:
        if not isinstance(batches, list):
            raise EvidenceRejected("batches_required")
        for batch in batches:
            validate_batch(batch)
            owner = batch["owner_id"]
            member = [str(bar["user_id"]), bar["code"]]
            if (
                batch["run_date"] != str(bar["data_date"])
                or (owner is None and member not in batch["members"])
                or (owner is not None and owner != str(bar["user_id"]))
                or batch["licence_id"] not in {None, str(bar["licence_id"])}
            ):
                raise EvidenceRejected("batch:bar_scope_or_date")
    if pipeline_run_id is not None and str(pipeline_run_id) not in [b["run_id"] for b in batches]:
        raise EvidenceRejected("pipeline_run_binding")
    hashed = {
        "proof": proof,
        "is_final": is_final,
        "available_at": available_at,
        "bar_version_id": bar_version_id,
    }
    return _save(
        conn,
        completions,
        dict(
            hashed,
            id=uuid4(),
            pipeline_run_id=pipeline_run_id,
            proof_kind=proof_kind,
            proof_hash=canon_sha256(hashed),
        ),
        ["bar_version_id", "proof_hash"],
    )
