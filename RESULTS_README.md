# Experiment artifact archive

The completed experiment outputs are preserved in the lossless archive
[`archives/experiment_artifacts_2026-09-29.tar.gz`](archives/experiment_artifacts_2026-09-29.tar.gz).
The archive is the canonical copy published with this repository. It keeps the
repository small enough to clone while retaining every generated record,
certificate, report, log, and hidden-evaluation output from the completed runs.

## Archive integrity

| Item | Value |
|---|---|
| Archive size | approximately 7 MB |
| SHA-256 | `FF427ECF7332B9BCE0CE5F93301FC615CA41EB9EE9BC85315E5F435AF7ABD946` |
| Entries | 6,349 |

Verify and extract on Windows PowerShell:

```powershell
Get-FileHash archives/experiment_artifacts_2026-09-29.tar.gz -Algorithm SHA256
tar -xzf archives/experiment_artifacts_2026-09-29.tar.gz -C .
```

Extraction recreates the historical `artifacts/` and `artifacts_*` directories
at the repository root. These extracted directories are intentionally ignored
by Git, so unpacking them will not create accidental commits. The archive can
be extracted again on a fresh machine whenever the historical records are
needed.

## Directory inventory after extraction

| Directory | Role |
|---|---|
| `artifacts/` | Stage-3 prototype outputs and certificates |
| `artifacts_hardened/` | Hardened prototype output layout |
| `artifacts_pilot/` | Stage-4 candidate-level pilot |
| `artifacts_reports/` | Curated paper-facing reports and corrected statistics |
| `artifacts_formal/` | Formal 180-candidate runs and certificates |
| `artifacts_multiround/` | Persistent multi-round runs, ablations, and final exams |
| `artifacts_ood/` | Independent OOD challenge and seal |
| `artifacts_llm/` | Ollama and Qwen proposal tracks, including Gate reports |

## Start with these files

After extraction, the most useful paper-facing files are:

- `artifacts_reports/stage4-results-corrected-v1/paper_results_corrected.md`
- `artifacts_reports/stage4-results-corrected-v1/multiround_final_corrected_summary.csv`
- `artifacts_reports/formal-v1-final2-report/paper_results.md`
- `artifacts_pilot/stage4-candidate-pilot-seed-17/main_results.md`
- `artifacts_ood/ood-challenge-v1/ood_main.csv`
- `artifacts_llm/ollama_pilot_v3b/reports/OFFLINE_SUMMARY.json`
- `artifacts_llm/qwen_track_v3/reports/gate_b.json`

The Qwen V3 record is an important negative result: it completed the
online/offline protocol but did not pass the pre-registered candidate-diversity
Gate B. It must not be presented as a successful external-validity
confirmation.

## Data-boundary and privacy notes

- `configs/*_offline.json` is intentionally not tracked. Those files contain
  hidden master seeds and remain local to the machine that ran the experiment.
- The archive contains historical post-hoc hidden labels, commitments, and raw
  LLM responses because they are part of the reproducibility record. They must
  not be read while designing or tuning a new online track.
- `HIDDEN_COMMITMENT.json` files contain commitments, not the underlying seeds.
- API keys are never stored in the archive. Provider credentials must be set in
  local environment variables only.
- The archive is a historical snapshot. Do not overwrite extracted runs;
  create a new output directory and a new seal for every new experiment.

## Reproduction rules

1. Clone the repository and install the environment as described in
   [`README.md`](README.md).
2. Extract the archive only when you need to inspect old results.
3. Run new online/offline experiments in a fresh directory under `artifacts_*`.
4. Keep the online and offline phases separated and preserve their phase locks.
5. Record new provenance in `PROJECT_PROGRESS.md` or a new report rather than
   editing the archived historical snapshot.

The source code and the historical result archive are intentionally separate:
changing an extracted artifact does not change the implementation, and changing
the implementation does not silently rewrite an earlier result.
