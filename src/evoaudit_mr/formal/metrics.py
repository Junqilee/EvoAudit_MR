"""Pre-registered admission metrics used only after hidden labels are revealed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


@dataclass(frozen=True)
class Confusion:
    """Confusion counts where positive means a hidden-reliable update."""

    tp: int
    fp: int
    tn: int
    fn: int
    severe_false_commits: int = 0

    @property
    def accepted(self) -> int:
        return self.tp + self.fp

    @property
    def unreliable(self) -> int:
        return self.fp + self.tn

    @property
    def reliable(self) -> int:
        return self.tp + self.fn

    @property
    def far(self) -> float | None:
        """False acceptance rate: FP / (FP + TN)."""
        return _ratio(self.fp, self.unreliable)

    @property
    def fdr(self) -> float | None:
        """False discovery rate: FP / (TP + FP)."""
        return _ratio(self.fp, self.accepted)

    @property
    def ap(self) -> float | None:
        return _ratio(self.tp, self.accepted)

    @property
    def uur(self) -> float | None:
        return _ratio(self.tp, self.reliable)

    @property
    def svr(self) -> float | None:
        return _ratio(self.severe_false_commits, self.accepted)

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "far": self.far,
            "fdr": self.fdr,
            "ap": self.ap,
            "uur": self.uur,
            "svr": self.svr,
        }


def confusion_from_pairs(
    pairs: Iterable[tuple[bool, bool, bool]],
) -> Confusion:
    """Build counts from ``(committed, reliable, severe_failure)`` tuples."""
    tp = fp = tn = fn = severe_false_commits = 0
    for committed, reliable, severe in pairs:
        if committed and reliable:
            tp += 1
        elif committed and not reliable:
            fp += 1
            severe_false_commits += int(severe)
        elif not committed and reliable:
            fn += 1
        else:
            tn += 1
    return Confusion(tp=tp, fp=fp, tn=tn, fn=fn, severe_false_commits=severe_false_commits)
