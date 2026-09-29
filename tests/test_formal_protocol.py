from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.formal.bootstrap import create_protocol_files
from evoaudit_mr.formal.audit import route_formal_probes
from evoaudit_mr.formal.catalogue import build_formal_events, mechanism_cluster
from evoaudit_mr.formal.metrics import Confusion
from evoaudit_mr.formal.protocol import ProtocolError, manifest_digest, require_online_complete
from evoaudit_mr.runners.results_correction import corrected_thinning_rows
from evoaudit_mr.runners.formal_candidates import run_offline, run_online


class FormalProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_formal_catalogue_is_180_events_with_opaque_metadata(self) -> None:
        events = build_formal_events()
        self.assertEqual(180, len(events))
        self.assertEqual({"AliasTool", "SwitchRule", "PermissionPath"}, {event.environment for event in events})
        self.assertEqual(30, len({mechanism_cluster(event) for event in events}))
        self.assertEqual(180, len({event.event_id for event in events}))
        forbidden = ("shortcut", "unsafe", "regression", "archetype", "failure")
        for event in events:
            rendered = json.dumps(event.patch.to_dict(), sort_keys=True).lower()
            self.assertFalse(any(word in rendered for word in forbidden), event.patch.patch_id)

    def test_pre_registered_metric_definitions(self) -> None:
        confusion = Confusion(tp=3, fp=2, tn=6, fn=1, severe_false_commits=1)
        self.assertEqual(0.25, confusion.far)
        self.assertEqual(0.4, confusion.fdr)
        self.assertEqual(0.6, confusion.ap)
        self.assertEqual(0.75, confusion.uur)
        self.assertEqual(0.2, confusion.svr)
        self.assertIsNone(Confusion(tp=0, fp=0, tn=3, fn=0).fdr)

    def test_offline_requires_sealed_online_and_commitments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            public, offline = create_protocol_files(
                self.root,
                public_path=work / "manifest.json",
                offline_path=work / "offline.json",
                hidden_master_seed="ab" * 32,
            )
            output = work / "run"
            with self.assertRaises(ProtocolError):
                run_offline(public, offline, output)
            run_online(public, output)
            manifest = json.loads(public.read_text(encoding="utf-8"))
            require_online_complete(
                output,
                expected_manifest_hash=manifest_digest(manifest),
                expected_event_count=180,
            )
            run_offline(public, offline, output)
            self.assertTrue((output / "offline_hidden" / "events.jsonl").exists())
            self.assertTrue((output / "formal_main.csv").exists())
            with self.assertRaises(FileExistsError):
                run_offline(public, offline, output)

    def test_online_runner_import_graph_has_no_hidden_oracle(self) -> None:
        source = (self.root / "src" / "evoaudit_mr" / "runners" / "formal_candidates.py").read_text(encoding="utf-8")
        online_prefix = source.split("def run_offline", 1)[0]
        self.assertNotIn("from evoaudit_mr.formal.offline", online_prefix)

    def test_twelve_pair_audit_uses_distinct_task_instances(self) -> None:
        event = build_formal_events()[0]
        contract = json.loads((self.root / "configs" / "aliastool_contract.json").read_text(encoding="utf-8"))
        suite = route_formal_probes(event, budget_pairs=12, seed=19, contract=contract)
        self.assertEqual(12, len(suite.probes))
        self.assertEqual(12, len({probe.task.task_id for probe in suite.probes}))

    def test_matched_thinning_scores_unselected_candidates_as_rejects(self) -> None:
        labels = {
            "good": {"reliable": True, "reasons": []},
            "bad-a": {"reliable": False, "reasons": []},
            "bad-b": {"reliable": False, "reasons": []},
        }
        payload = {
            "comparisons": {
                "baseline": {
                    "samples": [{"seed": 1, "baseline_event_ids": ["bad-a"], "evoaudit_event_ids": ["good"]}]
                }
            }
        }
        rows = corrected_thinning_rows(labels, payload)
        baseline = next(row for row in rows if row["method"] == "baseline")
        self.assertEqual((0, 1, 1, 1), (baseline["tp"], baseline["fp"], baseline["tn"], baseline["fn"]))
        self.assertEqual(0.5, baseline["far"])
        self.assertEqual(0.0, baseline["uur"])

    def test_offline_rejects_modified_online_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            public, offline = create_protocol_files(
                self.root,
                public_path=work / "manifest.json",
                offline_path=work / "offline.json",
                hidden_master_seed="cd" * 32,
            )
            output = work / "run"
            run_online(public, output)
            log = output / "online" / "direct_commit" / "events.jsonl"
            log.write_text(log.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ProtocolError):
                run_offline(public, offline, output)


if __name__ == "__main__":
    unittest.main()
