from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.ood.catalogue import build_ood_events, mechanism_cluster
from evoaudit_mr.runners.ood_challenge import create_protocol_files, run_offline, run_online


class OODChallengeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_catalogue_is_disjoint_and_has_24_unseen_mechanism_families(self) -> None:
        events = build_ood_events()
        self.assertEqual(72, len(events))
        self.assertEqual(24, len({mechanism_cluster(event) for event in events}))
        self.assertTrue(all(event.patch.patch_id.startswith("ood-") for event in events))
        self.assertTrue(all("formal_" not in event.patch.candidate_adapter for event in events))

    def test_two_phase_ood_challenge_is_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            manifest, offline = create_protocol_files(
                self.root,
                public_path=work / "manifest.json",
                offline_path=work / "offline.json",
                hidden_master_seed="34" * 32,
            )
            output = work / "run"
            run_online(manifest, output)
            run_offline(manifest, offline, output)
            rows = (output / "ood_main.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(17, len(rows))  # header + 4 methods x (3 env + overall)
            candidate_rows = (output / "candidate_ood_offline.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(73, len(candidate_rows))


if __name__ == "__main__":
    unittest.main()
