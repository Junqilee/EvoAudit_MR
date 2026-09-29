"""Minimal harness executor used by all online and hidden audits."""

from __future__ import annotations

from evoaudit_mr.envs.aliastool import run_episode as run_aliastool_episode
from evoaudit_mr.envs.permissionpath import run_episode as run_permissionpath_episode
from evoaudit_mr.envs.switchrule import run_episode as run_switchrule_episode
from evoaudit_mr.types import AgentTask, AliasToolTask, EpisodeOutcome, Harness, PermissionPathTask, SwitchRuleTask


def execute(harness: Harness, task: AgentTask, seed: int = 0) -> EpisodeOutcome:
    if harness.typed_policy:
        from evoaudit_mr.llm.v3_executor import execute_typed_policy

        return execute_typed_policy(harness.typed_policy, task, seed=seed)
    if isinstance(task, AliasToolTask):
        return run_aliastool_episode(harness.adapter_name, task, seed)
    if isinstance(task, SwitchRuleTask):
        return run_switchrule_episode(harness.adapter_name, task, seed)
    if isinstance(task, PermissionPathTask):
        return run_permissionpath_episode(harness.adapter_name, task, seed)
    raise TypeError(f"Unsupported task type: {type(task).__name__}")
