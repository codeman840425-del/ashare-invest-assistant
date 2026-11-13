"""S2-7: audit a public delisting subset and observe the frozen F23 matcher.

Default is offline excerpt/list reconciliation; --raw-dir additionally binds the
original HTML bytes. --fetch visits only the four registered public notices,
sequentially without credentials or retries. JSON goes to stdout; no data writes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
STRATEGIES = HERE.parent
PINNED = {
    "T-R62/f23_lexicon_v3.yaml": "8a545da8eef56a30804a998f238d6a18c54469d3544840773d251d15922da05a",
    "T-R62/match_f23_v3.py": "46a5a9be0e3fa86265a616b01346b5791c81c5b687259e779f365fa20918d06c",
    "T-R65/manifests/termination_manifest.json": "88d488a328999caa61317b679dbc1f5b646629fe1fafb90a8ada103f47f42e28",
    "T-R65/build_termination_list.py": "2ebca0a912e8bde9b8d2919ca735b9d9e82ae3b2e2a65e62c1c4176a8e9b9766",
}
HOSTS = {"www.sse.com.cn", "disc.static.szse.cn"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def html_text(raw, encoding):
    parser = TextOnly()
    parser.feed(raw.decode(encoding, errors="strict"))
    return compact(" ".join(parser.parts))


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, STRATEGIES / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_pins():
    for path, expected in PINNED.items():
        require(
            digest((STRATEGIES / path).read_bytes()) == expected, f"pin changed: {path}"
        )


def validate_url(url):
    parsed = urlsplit(url)
    require(
        parsed.scheme == "https" and parsed.hostname in HOSTS,
        "unapproved public source",
    )
    require(
        not parsed.username and not parsed.password and not parsed.query,
        "unexpected URL fields",
    )
    require(parsed.port in (None, 443), "unexpected URL port")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect refused; review the registered public URL")


def fetch(source):
    validate_url(source["url"])
    request = urllib.request.Request(
        source["url"],
        headers={"User-Agent": "Mozilla/5.0 (public research; sequential)"},
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=40) as response:
        require(response.status == 200, "non-200 response")
        raw = response.read(2_000_001)
    require(len(raw) <= 2_000_000, "unexpected response size")
    return raw


def validate_source(source):
    validate_url(source["url"])
    require(re.fullmatch(r"[a-z0-9-]+", source["id"]) is not None, "invalid source id")
    require(source["http_status"] == 200, "source was not fetched successfully")
    require(
        re.fullmatch(r"[0-9a-f]{64}", source["raw_sha256"]) is not None,
        "invalid digest",
    )
    require(
        datetime.fromisoformat(source["fetched_at"]).utcoffset() is not None,
        "naive fetch time",
    )
    published = date.fromisoformat(source["published_date"])
    require(
        date.fromisoformat(source["published_label"][:10]) == published,
        "publication label/date mismatch",
    )
    effective = date.fromisoformat(source["delisting_date"])
    require(
        published <= effective,
        "publication after effective date; manual review required",
    )
    require(
        source["date_evidence"] in source["excerpt"],
        "date evidence missing from excerpt",
    )
    # An explicit source phrase, not the publication date or a calendar offset, supplies the date.
    phrase = source["date_evidence"]
    expected = f"{effective.year}年{effective.month}月{effective.day}日"
    require(expected in phrase, "effective date disagrees with source phrase")
    require(
        "摘牌" in phrase or "终止上市日期" in phrase, "not an effective-date statement"
    )
    require(source["title"].strip() and source["securities"], "empty source record")
    for security in source["securities"]:
        exchange, symbol = security["exchange"], security["symbol"]
        require(exchange in {"SH", "SZ"}, "unsupported exchange")
        expected_exchange = (
            "SH" if urlsplit(source["url"]).hostname == "www.sse.com.cn" else "SZ"
        )
        require(exchange == expected_exchange, "exchange/source-host mismatch")
        require(re.fullmatch(r"\d{6}", symbol) is not None, "six-digit string required")
        require(symbol in source["excerpt"], "security absent from source excerpt")
        require(security["share_class"] in {"A", "B"}, "unknown share class")
    return source


def verify_raw(source, raw, exact):
    if exact:
        require(
            digest(raw) == source["raw_sha256"], f"HTML digest changed: {source['id']}"
        )
    text = html_text(raw, source["encoding"])
    for field in ("title", "excerpt", "published_label"):
        require(compact(source[field]) in text, f"HTML lacks {field}: {source['id']}")
    return {
        "id": source["id"],
        "raw_sha256": digest(raw),
        "matches_archived_bytes": digest(raw) == source["raw_sha256"],
    }


def reconcile(sources, listed, matcher, termination):
    evidence, excluded, observations = {}, [], []
    seen_ids = set()
    for source in sources:
        validate_source(source)
        require(source["id"] not in seen_ids, "duplicate source id")
        seen_ids.add(source["id"])
        hit, categories, _ = matcher.match_detail(source["title"])
        observations.append(
            {
                "source": source["id"],
                "title": source["title"],
                "f23_hit": hit,
                "categories": categories,
            }
        )
        for security in source["securities"]:
            key = (security["exchange"], security["symbol"])
            prefixes = (
                termination.SH_A_PREFIXES
                if key[0] == "SH"
                else termination.SZ_A_PREFIXES
            )
            if security["share_class"] == "B":
                require(
                    key[1].startswith("900" if key[0] == "SH" else "200"),
                    "B-share class/code mismatch",
                )
                excluded.append(":".join(key))
                continue
            require(key[1].startswith(prefixes), "A-share class/code mismatch")
            require(key not in evidence, "duplicate exchange/symbol evidence")
            evidence[key] = (source["delisting_date"], source["url"])
    actual = {}
    for row in listed:
        key = (row["exchange"], row["symbol"])
        require(key not in actual, "duplicate list key")
        actual[key] = (row["delisting_date"], row["source_url"])
    require(actual == evidence, "public subset differs from notice evidence")
    return evidence, excluded, observations


def audit(raw_dir=None, online=False):
    check_pins()
    registry = json.loads((HERE / "public_sources.json").read_text(encoding="utf-8"))
    sources = registry["sources"]
    require(len(sources) == 4, "registered scope must remain four notices")
    with (HERE / "termination_public_subset.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        listed = list(csv.DictReader(handle))
    matcher = load_module("s2_f23_v3", "T-R62/match_f23_v3.py")
    termination = load_module("s2_termination", "T-R65/build_termination_list.py")
    evidence, excluded, observations = reconcile(sources, listed, matcher, termination)
    raw_checks = []
    for index, source in enumerate(sources):
        if online or raw_dir:
            if online and index:
                time.sleep(1.5)
            raw = (
                fetch(source)
                if online
                else (raw_dir / f"{source['id']}.html").read_bytes()
            )
            raw_checks.append(verify_raw(source, raw, exact=not online))
    historical = json.loads(
        (STRATEGIES / "T-R65/manifests/termination_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    missing = {tuple(key) for key in historical["checks"]["missing_url"]}
    return {
        "scope": "four purposively selected notices; not a complete exchange list or F23 accuracy sample",
        "mode": "live public HTML"
        if online
        else "archived HTML"
        if raw_dir
        else "offline excerpts only",
        "pinned_inputs": PINNED,
        "source_notices": len(sources),
        "a_share_rows": len(evidence),
        "excluded_b_share_keys": sorted(excluded),
        "historical_missing_url_keys_with_new_evidence": sorted(
            ":".join(key) for key in evidence.keys() & missing
        ),
        "notice_date_differences": [
            {
                "source": s["id"],
                "published": s["published_date"],
                "delisted": s["delisting_date"],
            }
            for s in sources
            if s["published_date"] != s["delisting_date"]
        ],
        "f23_title_observations": observations,
        "raw_checks": raw_checks,
        "limits": "No original 337-row CSV/DB comparison, no whole-list completeness/date verdict, no FP/FN estimate; title non-hit does not change frozen policy.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--raw-dir", type=Path)
    group.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.raw_dir, args.fetch), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
