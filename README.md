# EvoAudit-MR

EvoAudit-MR is a reproducible research prototype for **patch-conditioned metamorphic auditing** of self-evolving agents. It studies how an agent should decide whether to adopt a proposed update when the update may improve the target task while silently breaking replay behavior or safety constraints.

The repository contains deterministic compact environments (`AliasTool`, `SwitchRule`, and `PermissionPath`), metamorphic-relation audits, online/offline hidden evaluation protocols, persistent-evolution runners, and optional LLM proposal tracks. The core package uses only the Python standard library at runtime.

## Current research status

The controlled Stage-4 experiments and the independent OOD challenge are implemented. The Qwen proposal pipeline has completed its public schema gate and a sealed online/offline run; the latest Qwen run did not meet the pre-registered candidate-diversity Gate B, so it is recorded as a limitation rather than presented as positive external-validity evidence.

See the Chinese project status and next-step plan in [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md). Research notes and the ICLR source are under [`docs/research/`](docs/research/) and [`paper/`](paper/).

## Requirements

- Windows PowerShell or an equivalent shell
- Python 3.10 or newer
- No GPU is required for the deterministic experiments
- Optional LLM tracks require a Qwen or DeepSeek API key; keys are read from environment variables only
- Optional local Ollama experiments require a separately installed Ollama service and model

The package has no third-party runtime dependency. `requirements.txt` installs the project in editable mode.

## Fresh-machine setup

```powershell
git clone https://github.com/Junqilee/EvoAudit_MR.git
cd EvoAudit_MR

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the full local test suite:

```powershell
python -m unittest discover -s tests -v
```

If editable installation is not desired, use the source tree directly:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

## Reproducing the deterministic prototype

```powershell
python -m evoaudit_mr.runners.prototype_demo --manifest configs/prototype_manifest.json
```

The runner creates local artifacts under `artifacts/`; generated outputs are intentionally ignored by Git. The prototype compares direct commitment, a fixed held-out gate, a fixed random audit, and EvoAudit-MR on the same candidate events.

## Controlled experiments

The main deterministic runners are:

```powershell
# Stage-4 candidate-level pilot
python -m evoaudit_mr.runners.stage4_pilot --manifest configs/stage4_pilot_manifest.json

# Formal candidate-level protocol
python -m evoaudit_mr.runners.formal_candidates --phase online --manifest configs/formal_v1_manifest.json --output-dir artifacts_formal/<run>
python -m evoaudit_mr.runners.formal_candidates --phase offline --manifest configs/formal_v1_manifest.json --offline-config configs/formal_v1_offline.json --output-dir artifacts_formal/<run>

# Persistent multiround protocol
python -m evoaudit_mr.runners.multiround --phase online --manifest configs/multiround_v1_manifest.json --output-dir artifacts_multiround/<run>
python -m evoaudit_mr.runners.multiround --phase offline --manifest configs/multiround_v1_manifest.json --offline-config configs/formal_v1_offline.json --output-dir artifacts_multiround/<run>

# Independent OOD challenge
python -m evoaudit_mr.runners.ood_challenge --phase bootstrap
python -m evoaudit_mr.runners.ood_challenge --phase online
python -m evoaudit_mr.runners.ood_challenge --phase offline
```

Keep every run in a new output directory. Never overwrite a sealed online/offline record.

## LLM proposal tracks

The LLM client uses Python's standard-library HTTP support and an OpenAI-compatible endpoint. Do not put keys in source files, JSON configs, Git, or chat messages.

Configure a provider locally:

```powershell
.\scripts\configure_llm_api_keys.ps1 -Provider qwen
.\scripts\llm_env_status.ps1
```

Validate a public configuration without an API call:

```powershell
python -m evoaudit_mr.runners.llm_preflight --config configs/llm_proposal_v1_qwen.json --mode validate
```

The Qwen track is phase-locked: public compiler readiness and schema compatibility must pass before proposal generation; each proposal slot is called once; hidden labels are generated only after online artifacts are locked. The repository deliberately excludes `configs/*_offline.json` and all `artifacts_*` directories because they contain private seeds, hidden labels, or generated records.

## Repository layout

```text
src/evoaudit_mr/       Core environments, audits, evolution, protocols, and runners
tests/                 Standard-library unit and protocol tests
configs/               Public manifests and model configuration templates
scripts/               PowerShell setup and long-running-track helpers
PROJECT_PROGRESS.md    Chinese project status, conclusions, and next steps
requirements.txt       Reproducible installation entry point
docs/research/         Literature notes, stage plans, and implementation records
paper/                 ICLR 2027 LaTeX/BibTeX source (no build outputs)
```

## Reproducibility and data boundaries

Online evaluation sees only public tasks and candidate context. Offline evaluators use HMAC-committed private configuration and are run after phase locks. Generated artifacts are local by design; this prevents accidentally publishing API responses, hidden seeds, or test labels. To share a result, export a redacted summary or add a deliberately curated report under version control rather than committing an entire artifact directory.

## License and research use

This repository is an evolving research prototype. Before publication, review the licenses of any benchmark or external project cloned under `external/` and keep those third-party files outside this repository unless their licenses permit redistribution.
