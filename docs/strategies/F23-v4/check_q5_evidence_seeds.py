"""RV-05 P2-2 synthetic seed oracle, not a v4 matcher or F23 counting implementation.

Check only the two explicit evidence specifications and their single-omission cases.
Do not import runtime code, fetch announcements, open a sample set, or write an ID map.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

REQUIRED = {
    "subject": (
        "issuer_id",
        "event_entity_id",
        "relation",
        "case_id",
        "announcement_id",
        "source_ref",
        "quote",
    ),
    "identity": ("role", "case_id", "source_ref", "quote"),
    "amount": (
        "case_id",
        "source_ref",
        "quote",
        "currency",
        "issuer_share",
        "claimed_total_cny",
        "attributable_claim_cny",
        "supported",
        "paid_cny",
        "unresolved_claim_cny",
        "exposure_kind",
        "materiality_basis",
        "fx_conversion",
    ),
    "pit": (
        "entity_id",
        "report_ref",
        "audit_status",
        "period_end",
        "available_at",
        "denominator_kind",
        "denominator_currency",
        "denominator_cny",
        "quote",
        "latest_audited_check_ref",
        "latest_audited_check_at",
        "latest_audited_check_quote",
    ),
    "independent_impact": (
        "case_id",
        "source_ref",
        "quote",
        "observed_effect",
        "existing_hit_review_ref",
        "existing_hit_review_quote",
    ),
}
ORIGINAL_BLOB = "d4f5714c6771246bf5c3e59f6b4f428ee25980a2"
AUTHORITY = "28a7f8ecb93d51d762153aee144f9587cdeccb93"


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("an explicit time zone is required")
    return parsed


def number(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("missing or boolean numeric evidence")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("non-finite number")
    return parsed


def numeric_branch(profile: str, amount: Decimal, denominator: Decimal) -> str:
    """Compare exact products, with no division, percentage rounding or fallback profile."""
    if profile == "sse_main_2026_04":
        if denominator == 0:
            return "unknown"
        passed = amount > 10000000 and amount * 10 >= abs(denominator)
        return "above_numeric_line" if passed else "below_numeric_line"
    if profile == "sse_star_2026_04" and denominator > 0:
        if amount <= 10000000:
            return "below_numeric_line"
        if amount * 100 >= denominator:
            return "above_numeric_line"
        return "unknown"  # Asset branch false, unused market-value branch unavailable.
    return "unknown"


def evidence_complete(case: dict) -> bool:
    """Fixed synthetic premise checks; quotation semantics still need human review."""
    try:
        if case.get("synthetic_only") is not True:
            return False
        evidence = case["evidence"]
        for group, fields in REQUIRED.items():
            record = evidence[group]
            if not isinstance(record, dict) or any(
                key not in record or record[key] is None for key in fields
            ):
                return False
            for key, value in record.items():
                if key.endswith("_ref") and not str(value).startswith(
                    f"synthetic:{case['original_case']}/"
                ):
                    return False
                if (key == "quote" or key.endswith("_quote")) and not str(
                    value
                ).startswith("【纯合成】"):
                    return False
        subject, identity, amount, pit, impact = (evidence[key] for key in REQUIRED)
        if not (
            subject["issuer_id"] == subject["event_entity_id"] == pit["entity_id"]
            and subject["relation"] == "issuer_self"
            and subject["issuer_id"] == f"SYN-ISSUER-{case['original_case']}"
            and subject["announcement_id"] == f"SYN-ANN-{case['original_case']}"
        ):
            return False
        if any(
            record["case_id"] != subject["case_id"]
            for record in (identity, amount, impact)
        ):
            return False
        if subject["case_id"] != f"SYN-CASE-{case['original_case']}" or identity[
            "role"
        ] not in {"defendant", "respondent"}:
            return False
        supported = amount["supported"]
        if not (
            isinstance(supported, dict)
            and supported.get("status") == "not_adjudicated_as_of"
            and "amount_cny" in supported
            and supported["amount_cny"] is None
        ):
            return False
        if not (
            amount["currency"] == pit["denominator_currency"] == "CNY"
            and amount["fx_conversion"].get("status") == "not_required_cny"
            and amount["materiality_basis"] == "attributable_claim_cny"
            and amount["exposure_kind"] == "disputed_claim_not_recognized_loss"
        ):
            return False
        claim = number(amount["claimed_total_cny"])
        share = number(amount["issuer_share"])
        attributed = number(amount["attributable_claim_cny"])
        paid = number(amount["paid_cny"])
        unresolved = number(amount["unresolved_claim_cny"])
        if not (
            claim > 0
            and 0 < share <= 1
            and claim * share == attributed
            and paid >= 0
            and unresolved >= 0
            and paid + unresolved == attributed
        ):
            return False
        as_of = moment(case["as_of"])
        available = moment(pit["available_at"])
        if not (
            moment(case["announcement_available_at"]) <= as_of
            and date.fromisoformat(pit["period_end"]) <= available.date()
            and available <= as_of
            and moment(pit["latest_audited_check_at"]) == as_of
            and pit["audit_status"] == "audited"
        ):
            return False
        expected_kind = {
            "sse_main_2026_04": "audited_net_assets",
            "sse_star_2026_04": "audited_total_assets",
        }
        if pit["denominator_kind"] != expected_kind.get(case["profile"]):
            return False
        return impact["observed_effect"] == "unresolved_adverse_payment_claim"
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        return False


def specification_route(case: dict) -> tuple[str, list]:
    retained = copy.deepcopy(case.get("existing_hits", []))
    if not evidence_complete(case):
        return "needs_evidence", retained
    amount, pit = case["evidence"]["amount"], case["evidence"]["pit"]
    try:
        branch = numeric_branch(
            case["profile"],
            number(amount["attributable_claim_cny"]),
            number(pit["denominator_cny"]),
        )
    except (ValueError, InvalidOperation):
        branch = "unknown"
    return {
        "above_numeric_line": "risk_candidate",
        "below_numeric_line": "observe",
        "unknown": "needs_evidence",
    }[branch], retained


def parent_at(record: dict, path: list[str]) -> dict:
    for key in path[:-1]:
        record = record[key]
    return record


def verify(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    results = []

    def check(label: str, ok: bool, **detail: object) -> None:
        results.append({"case": label, "passed": bool(ok), **detail})

    original_raw = path.with_name("q5_candidate_cases.yaml").read_bytes()
    blob = hashlib.sha1(
        b"blob " + str(len(original_raw)).encode() + b"\0" + original_raw,
        usedforsecurity=False,
    ).hexdigest()
    check(
        "original_18_seeds_unchanged",
        blob == ORIGINAL_BLOB == data["original_seeds"]["blob"]
        and hashlib.sha256(original_raw).hexdigest()
        == data["original_seeds"]["sha256"],
    )
    check(
        "authority_and_scope",
        data["authority"]["sha"] == AUTHORITY
        and data["synthetic_only"] is True
        and data["scope"]
        == "pure_synthetic_regression_specification_not_v4_implementation",
    )
    check(
        "required_field_matrix",
        data["required_evidence_fields"]
        == {key: list(value) for key, value in REQUIRED.items()},
    )
    expected_paths = {("as_of",), ("announcement_available_at",)}
    for group, fields in REQUIRED.items():
        expected_paths.add(("evidence", group))
        expected_paths.update(("evidence", group, field) for field in fields)
    expected_paths.update(
        {
            ("evidence", "amount", "supported", "status"),
            ("evidence", "amount", "supported", "amount_cny"),
            ("evidence", "amount", "fx_conversion", "status"),
        }
    )
    omissions = data["missing_evidence_cases"]
    check(
        "each_required_omission_explicit",
        len(omissions) == len(expected_paths)
        and {tuple(item["delete"]) for item in omissions} == expected_paths
        and all(item["expected_full_route"] == "needs_evidence" for item in omissions),
    )
    positives = {case["id"]: case for case in data["positive_cases"]}
    check(
        "exactly_L03_L05_positive_overlays",
        set(positives) == {"L03-FIVE-EVIDENCE", "L05-FIVE-EVIDENCE"},
    )
    original = {case["id"]: case for case in yaml.safe_load(original_raw)["cases"]}
    for seed in positives.values():
        route, retained = specification_route(seed)
        check(
            seed["id"],
            route == seed["expected"]["full_route"] == "risk_candidate"
            and retained == seed["existing_hits"]
            and seed["expected"]["count_mapping_written"] is False,
            route=route,
            retained_existing_hits=retained,
        )
        old = original[seed["original_case"]]
        old_route, _ = specification_route(old)
        check(
            seed["original_case"] + "-ORIGINAL-FACTS",
            old_route
            == data["original_facts_full_route"][old["id"]]
            == "needs_evidence",
            route=old_route,
        )
        denominator_key = (
            "audited_net_assets_cny"
            if old["id"] == "L03"
            else "audited_total_assets_cny"
        )
        branch = numeric_branch(
            old["profile"],
            number(old["facts"]["amount_cny"]),
            number(old["facts"][denominator_key]),
        )
        check(
            seed["original_case"] + "-AMOUNT-UNCHANGED",
            branch
            == seed["expected"]["numeric_materiality"]
            == old["proposed_materiality"]
            and number(seed["evidence"]["amount"]["attributable_claim_cny"])
            == number(old["facts"]["amount_cny"])
            and number(seed["evidence"]["pit"]["denominator_cny"])
            == number(old["facts"][denominator_key]),
        )
        for omission in omissions:
            missing = copy.deepcopy(seed)
            parent_at(missing, omission["delete"]).pop(omission["delete"][-1])
            actual, retained = specification_route(missing)
            check(
                seed["id"] + "/" + omission["id"],
                actual == omission["expected_full_route"]
                and retained == seed["existing_hits"],
                route=actual,
                deleted=omission["delete"],
            )
    for variant in data["variant_cases"]:
        seed = positives[variant["case"]]
        changed = copy.deepcopy(seed)
        for path_to_delete in variant.get("delete", []):
            parent_at(changed, path_to_delete).pop(path_to_delete[-1])
        for update in variant.get("set", []):
            parent_at(changed, update["path"])[update["path"][-1]] = update["value"]
        actual, retained = specification_route(changed)
        check(
            variant["id"],
            actual == variant["expected_full_route"]
            and retained == seed["existing_hits"],
            route=actual,
        )
    return {
        "scope": data["scope"],
        "authority": AUTHORITY,
        "original_seed_blob": blob,
        "positive_cases": len(positives),
        "single_omission_cases": len(omissions) * len(positives),
        "variants": len(data["variant_cases"]),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "runtime_or_counting_tested": False,
        "checks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        type=Path,
        default=Path(__file__).with_name("q5_l03_l05_evidence_cases.yaml"),
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.seeds)
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"Seed specification invalid: {type(exc).__name__}: {exc}")
        return 2
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        f"Synthetic evidence specification: {report['passed']}/{report['total']}; "
        f"positives={report['positive_cases']}; omissions={report['single_omission_cases']}; "
        f"variants={report['variants']}; runtime/count mapping not executed"
    )
    for item in report["checks"]:
        if not item["passed"]:
            print("FAIL " + item["case"])
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
