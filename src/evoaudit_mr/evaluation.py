"""Shared execution primitives that contain no online-audit or hidden policy."""

from __future__ import annotations

from evoaudit_mr.harness import execute
from evoaudit_mr.types import CandidateEvent, Probe, ProbeResult


def paired_results(event: CandidateEvent, probes: tuple[Probe, ...]) -> tuple[ProbeResult, ...]:
    return tuple(
        ProbeResult(
            probe=probe,
            parent=execute(event.parent, probe.task),
            candidate=execute(event.candidate, probe.task),
        )
        for probe in probes
    )


def mean_delta(results: tuple[ProbeResult, ...]) -> float:
    return sum(result.success_delta for result in results) / len(results) if results else 0.0
