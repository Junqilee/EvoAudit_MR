from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.evolution.engine import (
    SUPPLEMENTARY_ABLATION_METHODS,
    advance,
    initial_harness,
)
from evoaudit_mr.evolution.offline import evaluate_final, shared_final_exam
from evoaudit_mr.evolution.scenario import build_scenarios
from evoaudit_mr.evolution.state import EvolutionState
from evoaudit_mr.formal.bootstrap import create_protocol_files
from evoaudit_mr.formal.protocol import manifest_digest
from evoaudit_mr.runners.multiround import run_offline, run_online


class MultiRoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.contracts = {
            environment: json.loads((self.root / "configs" / filename).read_text(encoding="utf-8"))
            for environment, filename in {
                "AliasTool": "aliastool_contract.json",
                "SwitchRule": "switchrule_contract.json",
                "PermissionPath": "permissionpath_contract.json",
            }.items()
        }

    def test_commit_and_reject_have_persistent_state_semantics(self) -> None:
        state = EvolutionState.initial("AliasTool", initial_harness("AliasTool"))
        scenarios = build_scenarios("AliasTool", trajectory_seed=4)
        observed_commit = observed_reject = False
        for scenario in scenarios:
            parent_hash = state.working.state_hash
            state, record = advance(
                state,
                scenario,
                method="evoaudit_mr",
                contract=self.contracts["AliasTool"],
            )
            if record.committed:
                observed_commit = True
                self.assertNotEqual(parent_hash, state.working.state_hash)
            else:
                observed_reject = True
                self.assertEqual(parent_hash, state.working.state_hash)
        self.assertTrue(observed_commit)
        self.assertTrue(observed_reject)
        self.assertGreaterEqual(len(state.history), 2)

    def test_shared_final_exam_is_method_independent(self) -> None:
        exam_a = shared_final_exam(
            "PermissionPath",
            trajectory_seed=7,
            master_key="ef" * 32,
            manifest_hash="manifest-hash",
        )
        exam_b = shared_final_exam(
            "PermissionPath",
            trajectory_seed=7,
            master_key="ef" * 32,
            manifest_hash="manifest-hash",
        )
        self.assertEqual(
            [probe.to_dict() for probe in exam_a.probes],
            [probe.to_dict() for probe in exam_b.probes],
        )
        self.assertEqual(90, len(exam_a.probes))
        self.assertEqual({"target", "replay", "safety"}, {probe.bucket for probe in exam_a.probes})

    def test_final_safety_metrics_distinguish_probe_rate_from_event_density(self) -> None:
        state = EvolutionState.initial("AliasTool", initial_harness("AliasTool"))
        exam = shared_final_exam(
            "AliasTool", trajectory_seed=1, master_key="ef" * 32, manifest_hash="metrics"
        )
        result = evaluate_final(state.working, exam)
        self.assertIn("unsafe_probe_rate", result)
        self.assertIn("safety_event_density", result)
        self.assertLessEqual(float(result["unsafe_probe_rate"]), 1.0)

    def test_component_ablation_methods_preserve_the_six_pair_budget(self) -> None:
        state = EvolutionState.initial("AliasTool", initial_harness("AliasTool"))
        scenario = build_scenarios("AliasTool", trajectory_seed=1)[0]
        for method in SUPPLEMENTARY_ABLATION_METHODS:
            _, record = advance(
                state,
                scenario,
                method=method,
                contract=self.contracts["AliasTool"],
            )
            self.assertEqual(6, record.decision.bucket_summary["logical_pairs"])

    def test_multiround_online_imports_no_offline_module(self) -> None:
        source_path = self.root / "src" / "evoaudit_mr" / "runners" / "multiround.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        top_level_imports = [
            node.module
            for node in module.body
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        self.assertNotIn("evoaudit_mr.formal.offline", top_level_imports)
        self.assertNotIn("evoaudit_mr.evolution.offline", top_level_imports)

    def test_three_round_two_environment_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            public, offline = create_protocol_files(
                self.root,
                public_path=work / "manifest.json",
                offline_path=work / "offline.json",
                hidden_master_seed="12" * 32,
            )
            manifest = json.loads(public.read_text(encoding="utf-8"))
            manifest.update(
                {
                    "manifest_version": "multiround-v1",
                    "trajectory_seeds": [1, 2],
                    "rounds": 10,
                    "final_hidden_tasks_per_bucket": 30,
                }
            )
            public.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            output = work / "run"
            run_online(public, output)
            run_offline(public, offline, output)
            rows = list(csv_rows(output / "multiround_main.csv"))
            self.assertTrue(rows)
            self.assertIn("evoaudit_mr", {row["method"] for row in rows})
            self.assertIn("working@T", {row["checkpoint"] for row in rows})
            self.assertIn("frozen_best", {row["checkpoint"] for row in rows})
            trajectory_rows = list(csv_rows(output / "trajectory_summary.csv"))
            self.assertTrue(trajectory_rows)
            self.assertIn("cumulative_false_commits", trajectory_rows[0])


def csv_rows(path: Path):
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


if __name__ == "__main__":
    unittest.main()
