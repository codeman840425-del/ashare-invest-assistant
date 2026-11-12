"""B-03 offline seeds and MockTransport callback; never connects to services."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import yaml

from selfchecks.b03_shapes import DISCLAIMER, MODELS, validate

ROOT = Path(__file__).resolve().parents[3]
DRAFT = ROOT / "reports/deepseek/B-03/draft.json"
RESOURCES = tuple(MODELS)
TYPE_NAMES = {
    "bars": "BarsResponse",
    "financials": "FinancialsResponse",
    "fund-flows": "FundFlowsResponse",
    "factors": "FactorsResponse",
    "announcements": "AnnouncementsResponse",
}


def allowlist() -> set[str]:
    config = yaml.safe_load((ROOT / "config/securities.yaml").read_text(encoding="utf-8"))
    return set(config["announcements"]["url_host_allowlist"])


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def seeds() -> dict[str, dict[str, Any]]:
    """Apply reviewed corrections to the preserved mechanical draft, then validate all cases."""
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    bodies = {resource: deepcopy(draft[resource]) for resource in RESOURCES}
    bodies["announcements"]["disclaimer"] = DISCLAIMER
    bodies["bars"].pop("sources")  # Contract and real dailyBars mock do not include this field.
    financial = bodies["financials"]["items"][0]
    financial.update(debt_ratio_pct="42.00", operating_cash_flow="87654321.00")
    for factor in bodies["factors"]["items"]:
        factor["feature_key"] = None  # Synthetic ids must not claim feature_catalog registration.
    bodies["factors"]["factor_set_version"] = "synthetic-2-factors"
    for announcement in bodies["announcements"]["items"]:
        announcement["url"] = None  # Both draft hosts are outside the configured allowlist.
    bodies["announcements"]["items"].sort(
        key=lambda row: (row["published_at"], row["id"]), reverse=True
    )
    result: dict[str, dict[str, Any]] = {resource: {} for resource in RESOURCES}

    def add(resource: str, case: str, body: dict[str, Any], code: str = "999999.SH") -> None:
        params = {"freq": body["freq"], "adjust": body["adjust"]} if resource == "bars" else {}
        result[resource][case] = {
            "request": {"path": f"/api/v1/securities/{code}/{resource}", "params": params},
            "response": body,
        }

    for resource, body in bodies.items():
        add(resource, "stock", body)
        missing = deepcopy(body)
        missing.update(items=[], data_status="unavailable", data_as_of=None)
        if resource != "bars":
            missing["sources"] = []
        key = resource.replace("-", "_")
        missing["gaps"] = [
            {"key": key, "reason": "data_licence_unavailable", "message": "合成证书不可用，无缓存"}
        ]
        if resource == "factors":
            missing["counts"] = {"total": 0, "by_category": {}}
        add(resource, "licence_unavailable", missing)
        if resource == "bars":
            pending = deepcopy(missing)
            pending.update(
                data_status="pending",
                gaps=[
                    {
                        "key": "bars",
                        "reason": "quota_deferred",
                        "message": "合成队列在途，未调用上游",
                    }
                ],
            )
            add(resource, "pending", pending)
            minute = deepcopy(body)
            minute.update(freq="1m", pre_close="10.00")
            minute["items"] = [
                dict(body["items"][0], t="2026-11-03T09:31:00+08:00", avg_price="10.00")
            ]
            add(resource, "minute", minute)
            continue
        etf = deepcopy(missing)
        etf["gaps"] = [{"key": key, "reason": "not_applicable", "message": "合成 ETF 不适用"}]
        if resource != "announcements":
            etf.update(security_code="510300.SH", name="合成 ETF 示例")
        add(resource, "etf", etf, "510300.SH")
        if resource != "announcements":
            index = deepcopy(etf)
            index.update(security_code="000001.SH", name="合成指数示例")
            index["gaps"] = [{"key": key, "reason": "no_source", "message": "合成指数无该数据源"}]
            add(resource, "index", index, "000001.SH")
    hosts = allowlist()
    for resource, cases in result.items():
        for entry in cases.values():
            validate(resource, entry["response"], hosts)
    return result


def generate(destination: Path) -> Path:
    """Publish a fresh synthetic bundle atomically, without replacing any prior file."""
    if destination.is_symlink() or destination.exists():
        raise FileExistsError("fixture destination must be fresh")
    if not destination.name or not destination.parent.is_dir():
        raise ValueError("fixture destination requires an existing parent")
    payloads = seeds()
    with tempfile.TemporaryDirectory(prefix=".b03-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        sums = {}
        for resource, cases in payloads.items():
            content = _json(cases).encode("utf-8")
            name = f"{resource}.json"
            (stage / name).write_bytes(content)
            sums[name] = _sha(content)
        manifest = {
            "synthetic": True,
            "application_routes": False,
            "upstream_calls": 0,
            "baseline": "465e02046fa8d971897603742497444f884e89a2",
            "draft_model": "deepseek/deepseek-flash",
            "draft_sha256": _sha(DRAFT.read_bytes()),
            "files": sums,
            "cases": sum(map(len, payloads.values())),
            "frontend_types": TYPE_NAMES,
            "known_frontend_gap": (
                "DataStatusBlock.data_as_of is string in baseline; "
                "empty-data cases require null under T-A53"
            ),
        }
        (stage / "manifest.json").write_bytes(_json(manifest).encode("utf-8"))
        stage.rename(destination)
    return destination


def read_bundle(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("unsafe fixture root")
    names = {f"{resource}.json" for resource in RESOURCES}
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("unsafe fixture manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not True or set(manifest["files"]) != names:
        raise ValueError("invalid synthetic fixture manifest")
    result = {}
    hosts = allowlist()
    for resource in RESOURCES:
        path = root / f"{resource}.json"
        if path.is_symlink() or _sha(path.read_bytes()) != manifest["files"][path.name]:
            raise ValueError("fixture digest mismatch or unsafe file")
        result[resource] = json.loads(path.read_text(encoding="utf-8"))
        for entry in result[resource].values():
            validate(resource, entry["response"], hosts)
    return result


class FixtureEndpoint:
    """An HTTPX MockTransport callback, with fake viewer states; never mount in FastAPI."""

    def __init__(self, root: Path, case: str = "stock") -> None:
        self.bundle = read_bundle(root)
        self.case = case

    @staticmethod
    def error(status: int, code: str) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"cache-control": "private, no-store"},
            json={
                "error": {
                    "code": code,
                    "message": "B-03 合成端点骨架",
                    "details": None,
                    "request_id": "synthetic-b03",
                },
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        viewer = request.headers.get("x-b03-viewer")
        if viewer is None:
            return self.error(401, "AUTH_REQUIRED")
        if viewer != "approved":
            return self.error(403, "ACCOUNT_NOT_APPROVED")
        if request.method != "GET":
            return self.error(405, "METHOD_NOT_ALLOWED")
        resource = request.url.path.rsplit("/", 1)[-1]
        entry = self.bundle.get(resource, {}).get(self.case)
        if (
            request.url.host != "b03.invalid"
            or entry is None
            or request.url.path != entry["request"]["path"]
        ):
            return self.error(404, "NOT_FOUND")
        if dict(request.url.params) != entry["request"]["params"]:
            return self.error(400, "VALIDATION_ERROR")
        return httpx.Response(
            200, headers={"cache-control": "private, no-store"}, json=entry["response"]
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output)
    print(_json({"synthetic": True, "resources": len(RESOURCES), "path": str(args.output)}))


if __name__ == "__main__":
    main()
