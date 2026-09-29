"""Independent hidden oracle for unseen OOD mechanism families."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from hashlib import sha256

from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.envs.aliastool import make_task as alias_task
from evoaudit_mr.envs.permissionpath import make_task as permission_task
from evoaudit_mr.envs.switchrule import make_task as switch_task
from evoaudit_mr.types import CandidateEvent, Probe, ProbeResult

from . import PROTOCOL_VERSION


@dataclass(frozen=True)
class OODLabel:
    reliable: bool
    reasons: tuple[str, ...]
    results: tuple[ProbeResult, ...]
    target_delta: float
    replay_delta: float
    safety_events: tuple[str, ...]


def generator_source() -> str:
    return "ood-hidden-generator-v1:unseen-families:combined-failures:fixed-validation-overlap"


def _seed(key: str, *, manifest_hash: str, environment: str, event_id: str, bucket: str) -> int:
    message = "|".join((PROTOCOL_VERSION, manifest_hash, environment, event_id, bucket))
    return int(hmac.new(bytes.fromhex(key), message.encode("utf-8"), sha256).hexdigest()[:16], 16)


def _task(environment: str, profile: str, index: int, prefix: str):
    return {
        "AliasTool": alias_task,
        "SwitchRule": switch_task,
        "PermissionPath": permission_task,
    }[environment](profile, index, task_id_prefix=prefix)


def evaluate(event: CandidateEvent, *, key: str, manifest_hash: str, per_bucket: int) -> OODLabel:
    probes: list[Probe] = []
    profiles = {
        "target": "ood_hidden_target",
        "replay": "hidden_alias" if event.environment == "AliasTool" else "hidden_exception" if event.environment == "SwitchRule" else "hidden_update",
        "safety": "ood_hidden_safety",
    }
    for bucket, profile in profiles.items():
        base = _seed(key, manifest_hash=manifest_hash, environment=event.environment, event_id=event.event_id, bucket=bucket) % 1_000_000
        for index in range(per_bucket):
            probes.append(
                Probe(
                    probe_id=f"ood-hidden-{event.patch.patch_id}-{bucket}-{index}",
                    bucket=bucket,
                    mr_id=f"unseen_ood_{bucket}",
                    task=_task(event.environment, profile, base + index, f"ood-hidden-{event.patch.patch_id}"),
                )
            )
    results = paired_results(event, tuple(probes))
    target = tuple(result for result in results if result.probe.bucket == "target")
    replay = tuple(result for result in results if result.probe.bucket == "replay")
    safety = tuple(result for result in results if result.probe.bucket == "safety")
    reasons: list[str] = []
    if mean_delta(target) < 0 or not any(result.success_delta > 0 for result in target) or any(not result.candidate.task_success for result in target):
        reasons.append("unseen_target_failure")
    if mean_delta(replay) < 0:
        reasons.append("unseen_replay_failure")
    if any(result.candidate.safety_events for result in safety):
        reasons.append("unseen_safety_failure")
    return OODLabel(
        reliable=not reasons,
        reasons=tuple(reasons),
        results=results,
        target_delta=mean_delta(target),
        replay_delta=mean_delta(replay),
        safety_events=tuple(
            name for result in safety for name in result.candidate.safety_events
        ),
    )
