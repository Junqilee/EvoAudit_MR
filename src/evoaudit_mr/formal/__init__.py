"""Frozen-protocol machinery for the formal EvoAudit-MR experiments.

The package intentionally separates online admission code from offline hidden
evaluation.  Online modules may import :mod:`evoaudit_mr.formal.protocol` and
:mod:`evoaudit_mr.formal.catalogue`, but never :mod:`evoaudit_mr.formal.offline`.
"""

from __future__ import annotations

PROTOCOL_VERSION = "formal-v1"

