"""Offline guard tests; mutations are synthetic and never alter the frozen inputs."""

import copy
import csv
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "public_audit", HERE / "check_public_sources.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PublicSourcesTest(unittest.TestCase):
    def setUp(self):
        self.sources = json.loads(
            (HERE / "public_sources.json").read_text(encoding="utf-8")
        )["sources"]
        with (HERE / "termination_public_subset.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            self.rows = list(csv.DictReader(handle))
        self.matcher = audit.load_module("test_f23", "T-R62/match_f23_v3.py")
        self.termination = audit.load_module(
            "test_termination", "T-R65/build_termination_list.py"
        )

    def reconcile(self):
        return audit.reconcile(self.sources, self.rows, self.matcher, self.termination)

    def test_public_subset_and_frozen_title_observations(self):
        result = audit.audit()
        self.assertEqual(result["a_share_rows"], 4)
        self.assertEqual(result["excluded_b_share_keys"], ["SH:900952", "SZ:200003"])
        self.assertEqual(
            result["historical_missing_url_keys_with_new_evidence"], ["SZ:000003"]
        )
        self.assertEqual(
            [r["f23_hit"] for r in result["f23_title_observations"]],
            [True, False, False, False],
        )
        self.assertEqual(len(result["notice_date_differences"]), 3)
        self.assertEqual(result["raw_checks"], [])

    def test_publication_date_cannot_replace_effective_date(self):
        self.rows[1]["delisting_date"] = "2026-06-22"
        with self.assertRaisesRegex(ValueError, "differs from notice"):
            self.reconcile()

    def test_effective_date_must_appear_in_explicit_source_phrase(self):
        self.sources[1]["delisting_date"] = "2026-06-22"
        with self.assertRaisesRegex(ValueError, "disagrees with source phrase"):
            self.reconcile()

    def test_duplicate_and_wrong_exchange_keys_are_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate list key"):
            self.reconcile()
        self.rows.pop()
        self.rows[0]["exchange"] = "SH"
        with self.assertRaisesRegex(ValueError, "differs from notice"):
            self.reconcile()

    def test_b_share_cannot_enter_a_share_subset(self):
        row = copy.deepcopy(self.rows[0])
        row["symbol"] = "200003"
        self.rows.append(row)
        with self.assertRaisesRegex(ValueError, "differs from notice"):
            self.reconcile()

    def test_html_digest_and_excerpt_guards(self):
        source = copy.deepcopy(self.sources[0])
        raw = (source["title"] + source["published_label"] + source["excerpt"]).encode(
            "gb18030"
        )
        source["raw_sha256"] = audit.digest(raw)
        audit.verify_raw(source, raw, exact=True)
        with self.assertRaisesRegex(ValueError, "digest changed"):
            audit.verify_raw(source, raw + b"!", exact=True)
        with self.assertRaisesRegex(ValueError, "HTML lacks excerpt"):
            audit.verify_raw(source, source["title"].encode("gb18030"), exact=False)

    def test_public_url_and_awareness_guards(self):
        with self.assertRaisesRegex(ValueError, "unapproved public source"):
            audit.validate_url("https://example.invalid/notice")
        self.sources[0]["fetched_at"] = "2026-11-12T18:27:10"
        with self.assertRaisesRegex(ValueError, "naive fetch time"):
            self.reconcile()


if __name__ == "__main__":
    unittest.main()
