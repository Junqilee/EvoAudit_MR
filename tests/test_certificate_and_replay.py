from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.runners.prototype_demo import run


class CertificateTests(unittest.TestCase):
    def test_demo_is_replayable_and_writes_certificates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            root = Path(__file__).resolve().parents[1]
            manifest = root / "configs" / "prototype_manifest.json"
            run(manifest, first)
            run(manifest, second)
            self.assertEqual((first / "summary.csv").read_text(encoding="utf-8"), (second / "summary.csv").read_text(encoding="utf-8"))
            certificate = json.loads((first / "evoaudit_mr" / "certificates" / "restricted_lookup_adapter.json").read_text(encoding="utf-8"))
            self.assertEqual("reject", certificate["decision"])
            self.assertIn("safety_invariant_failed", certificate["decision_reasons"])
            methods = ("direct_commit", "fixed_heldout", "fixed_random_audit", "evoaudit_mr")
            for method in methods:
                self.assertEqual(4, len(list((first / method / "certificates").glob("*.json"))))
                online_path = first / method / "online" / "events.jsonl"
                lines = online_path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(4, len(lines))
                self.assertTrue(all("hidden_label" not in json.loads(line) for line in lines))
            hidden_lines = (first / "offline_hidden" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(4, len(hidden_lines))
            self.assertTrue(all("hidden_label" in json.loads(line) for line in hidden_lines))

    def test_online_runner_has_no_hidden_import(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "src" / "evoaudit_mr" / "runners" / "online.py").read_text(encoding="utf-8")
        self.assertNotIn("evoaudit_mr.hidden", source)

    def test_hidden_generator_has_no_audit_import_and_adds_unseen_combinations(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "src" / "evoaudit_mr" / "hidden" / "generator.py").read_text(encoding="utf-8")
        self.assertNotIn("evoaudit_mr.audits", source)
        self.assertIn("alt_alias_reordered", source)
