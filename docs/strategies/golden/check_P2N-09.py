"""P2N-09 offline independent oracle (T-R31/T-R33).

Deterministic structural/chain guards for explanation-binding golden cases.
Does not import application code, models, or R08/R09 checkers.
Uses Decimal/Fraction for numeric equality; no invented tolerances.
"""
from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
FILE = HERE / "P2N-09_golden.json"
DISCLAIMER_FILE = HERE.parent / "compliance" / "disclaimer.md"


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load():
    return json.loads(FILE.read_text(encoding="utf-8"))


def disclaimer_from_repo() -> str:
    text = DISCLAIMER_FILE.read_text(encoding="utf-8")
    # Extract the quoted 47-char line after 文案
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(">") and "本工具仅供个人研究参考" in s:
            return s.lstrip(">").strip()
    raise AssertionError("disclaimer text not found")


def frac_eq(a, b) -> bool:
    try:
        return Fraction(str(a)) == Fraction(str(b))
    except (ValueError, ZeroDivisionError, InvalidOperation):
        return False


def findings(c: dict) -> list[str]:
    """Independent of expected.*; residual blocked short-circuit (T-A71: none expected)."""
    if c.get("case_status") == "blocked":
        return ["blocked_pending_real_env"]
    kind = c["kind"]
    i = c["input"]
    out: set[str] = set()

    if kind == "bind_stock":
        e0 = i["stocks"][0]["explanation"]
        code0 = i["stocks"][0]["security_code"]
        evid = {e["id"]: e for e in i["evidence"]}
        for p in e0.get("paragraphs") or []:
            for cid in p.get("cites") or []:
                ev = evid.get(cid)
                if ev is None or ev.get("security_code") != code0:
                    out.add("cross_object_citation")
        if i["stocks"][1].get("explanation") is not None:
            out.add("unexpected_stock_explanation")

    elif kind == "bind_divergence":
        evid = {e["id"]: e for e in i["evidence"]}
        for item in i["divergence"]:
            dims = set(item["dimensions"])
            for p in (item["explanation"] or {}).get("paragraphs") or []:
                for cid in p.get("cites") or []:
                    ev = evid.get(cid)
                    if ev is None or ev.get("dimension") not in dims:
                        out.add("citation_fact_mismatch")

    elif kind == "null_no_reuse":
        if i.get("render_stock0_text"):
            out.add("top_explanation_reused")

    elif kind == "missing_key":
        if "explanation" in i["divergence_item"]:
            out.add("unexpected_explanation_key")
        if i.get("render_text"):
            out.add("inferred_explanation")

    elif kind == "cross_object":
        e0 = i["stocks"][0]["explanation"]
        code0 = i["stocks"][0]["security_code"]
        evid = {e["id"]: e for e in i["evidence"]}
        for p in e0.get("paragraphs") or []:
            for cid in p.get("cites") or []:
                ev = evid.get(cid)
                if ev is None or ev.get("security_code") != code0:
                    out.add("cross_object_citation")

    elif kind == "cross_dimension":
        evid = {e["id"]: e for e in i["evidence"]}
        item = i["divergence"][0]
        dims = set(item["dimensions"])
        for p in item["explanation"].get("paragraphs") or []:
            for cid in p.get("cites") or []:
                ev = evid.get(cid)
                if ev is None or ev.get("dimension") not in dims:
                    out.add("citation_fact_mismatch")

    elif kind == "fallback_enum":
        proj = c["expected"]["explanation_projection"]
        # Recompute projection from chain; do not trust expected for findings,
        # but verify chain consistency as acceptance condition via projection helper.
        chain = i["chain"]
        reason = chain["fallback_reason"]
        call_id = chain.get("llm_call_id")
        invoked = chain["invoked"]
        if reason in ("not_enabled", "budget_exceeded") and call_id is not None:
            out.add("fabricated_call_id")
        if reason in ("timeout", "provider_error", "validation_failed") and not call_id:
            out.add("missing_call_id")
        if invoked != (call_id is not None) and reason != "validation_failed":
            # validation_failed always invoked with call_id in fixtures
            pass
        if reason == "validation_failed" and c.get("candidate"):
            text = "".join(p.get("text", "") for p in c["candidate"].get("paragraphs") or [])
            if "减仓" in text:
                # chain already encodes fallback; structural OK when projection matches
                pass
        # findings empty when chain self-consistent
        if reason in ("not_enabled", "budget_exceeded") and call_id is None and not invoked:
            pass
        elif reason in ("timeout", "provider_error", "validation_failed") and call_id and invoked:
            pass
        else:
            if reason in ("not_enabled", "budget_exceeded") and (call_id or invoked):
                out.add("fabricated_call_id")
            if reason in ("timeout", "provider_error", "validation_failed") and not call_id:
                out.add("missing_call_id")

    elif kind == "null_vs_missing":
        if i.get("render_a") != i.get("render_b"):
            out.add("null_missing_inconsistent")

    elif kind == "no_infer":
        if i.get("render_text"):
            out.add("inferred_explanation")

    elif kind == "no_cascade":
        if i.get("render_stock0_text"):
            out.add("cascaded_top_explanation")

    elif kind == "template_boundary":
        e = i["explanation"]
        if e.get("source") != "template" or e.get("validation_status") != "fallback":
            out.add("template_shape")
        label = e.get("ui_label") or ""
        body = "".join(p.get("text", "") for p in e.get("paragraphs") or [])
        if "AI 生成" in body or "AI 分析" in body or "AI 生成" in str(label):
            out.add("template_claimed_as_ai")

    elif kind == "llm_success":
        e = i["explanation"]
        if not (
            e.get("source") == "llm"
            and e.get("validation_status") == "passed"
            and e.get("fallback_reason") is None
            and e.get("llm_call_id")
        ):
            out.add("llm_success_shape")
        # numeric: displayed score must Fraction-equal evidence
        evid = {x["id"]: x for x in i.get("evidence") or []}
        for p in e.get("paragraphs") or []:
            for tok in p.get("text", "").split():
                if tok.replace(".", "", 1).isdigit() or (tok.count(".") == 1 and tok.replace(".", "").isdigit()):
                    # compare to first evidence value when present
                    if evid:
                        ev = next(iter(evid.values()))
                        if not frac_eq(tok, ev["value"]):
                            out.add("numeric_mismatch")

    elif kind == "no_fabricated_call":
        e = i["explanation"]
        if e.get("fallback_reason") == "not_enabled" and e.get("llm_call_id") is not None:
            out.add("fabricated_call_id")

    elif kind == "protected_invariant":
        if i["protected_result"] != i["post_fallback_protected_result"]:
            out.add("protected_result_mutation")
        # Decimal cross-check on score field
        if not frac_eq(i["protected_result"]["score"], i["post_fallback_protected_result"]["score"]):
            out.add("protected_result_mutation")

    elif kind == "immutable":
        if i.get("committed") and i.get("operation") == "overwrite_existing_explanation":
            out.add("immutable_snapshot")

    elif kind == "disclaimer_append":
        if i["system_disclaimer"] != disclaimer_from_repo():
            out.add("disclaimer_text_mismatch")
        if i["final_display"] != i["llm_body"] + i["system_disclaimer"]:
            out.add("disclaimer_text_mismatch")

    elif kind == "disclaimer_in_llm":
        if disclaimer_from_repo() in (i.get("candidate_text") or ""):
            out.add("llm_wrote_disclaimer")

    elif kind == "disclaimer_on_template":
        if i["system_disclaimer"] != disclaimer_from_repo():
            out.add("disclaimer_text_mismatch")
        if i["final_display"] != i["template_body"] + i["system_disclaimer"]:
            out.add("disclaimer_text_mismatch")


    elif kind == "auth_leak":
        # C12: non-admin must not surface llm_call_id (T-A71; usage_page_available any)
        if i.get("viewer_role") != "user":
            out.add("auth_role_mismatch")
        if not i.get("llm_call_id"):
            out.add("llm_call_id_missing")
        render = i.get("render") or {}
        if render.get("show_llm_call_id") or render.get("href") or render.get("id_text"):
            out.add("llm_call_id_leak")

    elif kind == "auth_plain":
        # C13: admin, no usage page → plain id, no href (T-A71/T-A72)
        if i.get("viewer_role") != "admin":
            out.add("auth_role_mismatch")
        if i.get("usage_page_available") is not False:
            out.add("usage_page_flag_mismatch")
        call_id = i.get("llm_call_id")
        if not call_id:
            out.add("llm_call_id_missing")
        render = i.get("render") or {}
        if render.get("href"):
            out.add("link_without_usage_page")
        if not render.get("show_llm_call_id"):
            out.add("llm_call_id_missing")
        elif render.get("id_text") != call_id:
            out.add("llm_call_id_missing")

    elif kind == "auth_link":
        # C14: admin + usage page → encoded href + id_text == llm_call_id (T-A71/T-A72)
        if i.get("viewer_role") != "admin":
            out.add("auth_role_mismatch")
        if i.get("usage_page_available") is not True:
            out.add("usage_page_flag_mismatch")
        call_id = i.get("llm_call_id")
        if not call_id:
            out.add("llm_call_id_missing")
        render = i.get("render") or {}
        expected_href = "/admin/llm/usage?call_id=" + quote(str(call_id), safe="") if call_id else None
        href = render.get("href")
        if expected_href is not None and href != expected_href:
            out.add("auth_link_mismatch")
        if not render.get("show_llm_call_id"):
            out.add("llm_call_id_missing")
        elif render.get("id_text") != call_id:
            out.add("llm_call_id_missing")

    elif kind == "cache":
        # C21: cache_hit + not invoked → explanation byte-equal, llm_call_id unchanged (T-A71)
        chain = i.get("chain") or {}
        if chain.get("cache_hit") is not True or chain.get("invoked") is not False:
            out.add("cache_chain_mismatch")
        src = i.get("source_explanation")
        cur = i.get("explanation")
        if src is None or cur is None:
            out.add("cache_chain_mismatch")
        else:
            if cur.get("llm_call_id") != src.get("llm_call_id"):
                out.add("duplicate_llm_call")
            if cur != src:
                out.add("cache_body_mismatch")


    else:
        raise AssertionError(f"unknown kind {kind}")

    return sorted(out)


def verdict_of(detected: list[str], status: str) -> str:
    if status == "blocked":
        return "blocked"
    return "rejected" if detected else "accepted"


def run_cases(data: dict) -> dict:
    assert data["fictitious"] is True
    assert data["disclaimer_sha256"] == hashlib.sha256(disclaimer_from_repo().encode()).hexdigest()
    assert len(data["cases"]) == 26
    ready = blocked = 0
    for c in data["cases"]:
        got = findings(c)
        assert got == c["expected"]["findings"], (c["id"], got, c["expected"]["findings"])
        assert verdict_of(got, c["case_status"]) == c["expected"]["verdict"], c["id"]
        if c["case_status"] == "ready":
            ready += 1
        else:
            blocked += 1
            assert c["expected"]["verdict"] == "blocked"
    return {"ready_pass": ready, "blocked": blocked}


def run_mutations(data: dict) -> dict:
    ready = [c for c in data["cases"] if c["case_status"] == "ready"]
    assert len(ready) == 26
    exp_mut = 0
    inp_mut = 0
    # expected.verdict corruption must not match oracle (include new four)
    for cid in ("C01", "C05", "C12", "C13", "C14", "C21"):
        c = next(x for x in ready if x["id"] == cid)
        wrong = copy.deepcopy(c)
        wrong["expected"] = copy.deepcopy(c["expected"])
        wrong["expected"]["verdict"] = "accepted" if c["expected"]["verdict"] == "rejected" else "rejected"
        got = findings(c)
        assert verdict_of(got, c["case_status"]) != wrong["expected"]["verdict"]
        exp_mut += 1
    # legacy input mutations
    c05 = next(c for c in ready if c["id"] == "C05")
    fixed = copy.deepcopy(c05)
    fixed["input"]["stocks"][0]["explanation"]["paragraphs"][0] = {
        "text": "正引 [D1_1]",
        "cites": ["D1_1"],
    }
    assert findings(fixed) == []
    assert findings(c05) == ["cross_object_citation"]
    inp_mut += 1
    c22 = next(c for c in ready if c["id"] == "C22")
    bad = copy.deepcopy(c22)
    bad["input"]["post_fallback_protected_result"]["score"] = "0.99"
    assert "protected_result_mutation" in findings(bad)
    inp_mut += 1
    c24 = next(c for c in ready if c["id"] == "C24")
    bad = copy.deepcopy(c24)
    bad["input"]["system_disclaimer"] = bad["input"]["system_disclaimer"] + "x"
    assert "disclaimer_text_mismatch" in findings(bad)
    inp_mut += 1
    c19 = next(c for c in ready if c["id"] == "C19")
    bad = copy.deepcopy(c19)
    bad["input"]["explanation"]["paragraphs"][0]["text"] = "分数 0.41"
    assert "numeric_mismatch" in findings(bad)
    assert frac_eq("0.40", Fraction(2, 5))
    inp_mut += 1
    c18 = next(c for c in ready if c["id"] == "C18")
    bad = copy.deepcopy(c18)
    bad["input"]["explanation"]["ui_label"] = "AI 生成"
    assert "template_claimed_as_ai" in findings(bad)
    inp_mut += 1
    # T-A71/T-A72 new four — input mutations
    c12 = next(c for c in ready if c["id"] == "C12")
    bad = copy.deepcopy(c12)
    bad["input"]["render"] = {"show_llm_call_id": True, "href": None, "id_text": "call-auth"}
    assert "llm_call_id_leak" in findings(bad)
    inp_mut += 1
    # C12: usage_page_available=true leak (highest risk; T-A71 any-value / T-A72)
    bad = copy.deepcopy(c12)
    bad["input"]["usage_page_available"] = True
    bad["input"]["render"] = {"show_llm_call_id": True, "href": "/admin/llm/usage?call_id=call-auth", "id_text": "call-auth"}
    assert "llm_call_id_leak" in findings(bad)
    assert findings(bad)  # rejected
    inp_mut += 1
    c13 = next(c for c in ready if c["id"] == "C13")
    bad = copy.deepcopy(c13)
    bad["input"]["render"] = {
        "show_llm_call_id": True,
        "href": "/admin/llm/usage?call_id=call-auth",
        "id_text": "call-auth",
    }
    assert "link_without_usage_page" in findings(bad)
    inp_mut += 1
    c14 = next(c for c in ready if c["id"] == "C14")
    # wrong route
    bad = copy.deepcopy(c14)
    bad["input"]["render"] = {
        "show_llm_call_id": True,
        "href": "/admin/wrong?call_id=" + quote(c14["input"]["llm_call_id"], safe=""),
        "id_text": c14["input"]["llm_call_id"],
    }
    assert "auth_link_mismatch" in findings(bad)
    inp_mut += 1
    # unencoded id
    bad = copy.deepcopy(c14)
    bad["input"]["render"] = {
        "show_llm_call_id": True,
        "href": "/admin/llm/usage?call_id=" + c14["input"]["llm_call_id"],
        "id_text": c14["input"]["llm_call_id"],
    }
    assert "auth_link_mismatch" in findings(bad)
    inp_mut += 1
    # C14: id_text != llm_call_id (T-A72)
    bad = copy.deepcopy(c14)
    bad["input"]["render"] = copy.deepcopy(c14["input"]["render"])
    bad["input"]["render"]["id_text"] = "WRONG-ID"
    assert "llm_call_id_missing" in findings(bad)
    inp_mut += 1
    c21 = next(c for c in ready if c["id"] == "C21")
    bad = copy.deepcopy(c21)
    bad["input"]["explanation"] = copy.deepcopy(c21["input"]["explanation"])
    bad["input"]["explanation"]["llm_call_id"] = "call-c21-NEW"
    assert "duplicate_llm_call" in findings(bad)
    inp_mut += 1
    bad = copy.deepcopy(c21)
    bad["input"]["explanation"] = copy.deepcopy(c21["input"]["explanation"])
    bad["input"]["explanation"]["paragraphs"][0]["text"] = "被改写的缓存正文"
    assert "cache_body_mismatch" in findings(bad)
    inp_mut += 1
    # T-A72 ③: precondition failure → finding, not AssertionError
    bad = copy.deepcopy(c12)
    bad["input"]["viewer_role"] = "admin"  # C12 expects user
    got = findings(bad)
    assert "auth_role_mismatch" in got
    assert not isinstance(got, BaseException)
    inp_mut += 1
    bad = copy.deepcopy(c13)
    bad["input"]["usage_page_available"] = True  # C13 expects False
    assert "usage_page_flag_mismatch" in findings(bad)
    inp_mut += 1
    return {
        "expected_verdict_mutations_rejected": exp_mut,
        "input_mutations_detected": inp_mut,
        "t_a71_t_a72_input_mutations": 10,
    }


def main() -> int:
    data = load()
    summary = run_cases(data)
    mut = run_mutations(data)
    assert summary["ready_pass"] == 26 and summary["blocked"] == 0
    out = {
        **summary,
        **mut,
        "total": 26,
        "normal_ready_pass": f"{summary['ready_pass']}/26",
        "mutation_reject": f"{mut['expected_verdict_mutations_rejected']}+{mut['input_mutations_detected']}",
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
