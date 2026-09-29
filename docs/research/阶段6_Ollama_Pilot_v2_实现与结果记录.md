# 阶段 6：Ollama LLM Proposal Pilot v2 实现与结果记录

**状态：已完成并封存（2026-08-13）**

## 1. 本轮目的与结论

本轮使用本地 `Ollama + qwen2.5:7b`，检验 EvoAudit-MR 能否在**受限策略族中的真实 LLM 提案**上执行更新审计。工程协议、候选生成、候选级审计、多轮持久演进、离线隐藏评测和封存均已跑通；但预注册的候选多样性验收门槛未通过。因此，本轮是一个成功完成的开发 Pilot，**不是**可用于论文主张方法优于基线的证据。

根因不是 EvoAudit-MR 被反驳，而是当前“自然语言提案 → 紧凑 DSL”的编译器覆盖过窄：本地模型大部分正确但措辞不同的提案未能编译成可执行行为，导致可供 gate 区分的可靠/不可靠候选不足。

## 2. 实现完成项

1. 本地 Ollama 客户端：仅允许 loopback endpoint，并检查版本、已安装模型和模型 digest。
2. 一次生成、零重试：每个 slot 恰好调用一次本地模型；invalid、unexecutable 和 no-op 均如实记账。
3. 两条评测轨道：
   - canonical candidate-level track：所有 gate 在同一 canonical parent 上审核同一提案；
   - shared-proposal persistent-evolution track：四个动态 gate 共享外生 proposal stream，但各自在自身 parent 上审核与应用；另有 Static 终局参照。
4. 公平基线：Direct、RSEA-style、Random 和 EvoAudit-MR 都先要求可见目标集 `D_e` 严格改善；Static 不更新。
5. 严格 online/offline 隔离：online 只使用公开 traces 和 gate；hidden label 与最终考卷仅在 offline 阶段导入。
6. 可审计封存：隐藏任务/seed 的 HMAC commitment、phase lock、在线源文件 hash、候选账本 hash 和最终 `PILOT_SEAL.json` 均已写入。

实现相关代码位于 `evoaudit_mr/src/evoaudit_mr/llm/` 与 `evoaudit_mr/src/evoaudit_mr/runners/ollama_pilot.py`。新增 mock 协议测试后，项目回归测试为 **45/45 passed**。

## 3. 冻结与运行配置

| 项目 | 结果 |
| --- | --- |
| 本地模型 | `qwen2.5:7b` |
| Ollama 版本 | `0.32.9` |
| 模型 digest | `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` |
| endpoint | `http://127.0.0.1:11434` |
| 真实提案调用 | 30（每 slot 一次，无重试） |
| 在线耗时 | 约 670 秒 |
| 环境 | AliasTool、PermissionPath |
| 轨迹 | 每环境 3 个 seed；4 个动态方法 + Static |

冻结记录：`evoaudit_mr/artifacts_llm/ollama_pilot_v2/OLLAMA_FREEZE.json`。

## 4. 预注册验收结果

| 验收项 | 阈值 | 实际 | 是否通过 |
| --- | ---: | ---: | --- |
| 可执行候选数 | `>= 18 / 30` | `10 / 30` | 否 |
| 两个环境均有可执行候选 | 是 | AliasTool 9；PermissionPath 1 | 是 |
| canonical 可靠候选数 | `>= 3` | 9 | 是 |
| canonical 不可靠候选数 | `>= 3` | 1 | 否 |
| raw proposal 唯一数 | 报告 | 30 | — |
| compiled intent 唯一数 | 报告 | 2 | — |
| behavior signature 唯一数 | 报告 | 2 | — |

其中，1 个提案为 invalid，19 个为 valid-but-unexecutable，1 个可执行提案为行为 no-op。可执行候选只有 9 个 semantic intent 和 1 个 visible-shortcut intent；这正是难以形成有辨识度的可靠/不可靠更新分布的原因。

## 5. 结果（仅描述性呈现）

### 5.1 候选级

在仅有的 10 个 executable canonical candidates 中，9 个可靠、1 个不可靠。Direct、RSEA-style 与 EvoAudit-MR 都保留 9 个可靠候选且未保留不可靠候选；Random 少保留 1 个可靠候选。由于不可靠候选只有 1 个，且该候选已不满足所有方法共享的 `D_e` 严格改善前提，**这里没有形成 gate 的有效区分压力**，不应解释为 EvoAudit-MR 的优势。

### 5.2 多轮终局

总体终局分数（6 条 environment-seed trajectories）为：Direct `0.778`、RSEA-style `0.778`、Random `0.667`、EvoAudit-MR `0.778`、Static `0.167`。EvoAudit-MR 与 Direct/RSEA-style 持平，不存在可报告的相对优势；这些数字也不做显著性检验或论文主张。

完整原始报告位于：

- `evoaudit_mr/artifacts_llm/ollama_pilot_v2/reports/generator_metrics.csv`
- `evoaudit_mr/artifacts_llm/ollama_pilot_v2/reports/candidate_metrics.csv`
- `evoaudit_mr/artifacts_llm/ollama_pilot_v2/reports/trajectory_summary.csv`
- `evoaudit_mr/artifacts_llm/ollama_pilot_v2/reports/pilot_report.md`

## 6. 科学解释与下一步

该 Pilot 支持的边界性结论是：系统能够对真实本地 LLM 产生的、受限 DSL 更新执行完整且可封存的审计流程。它**不支持**“EvoAudit-MR 在 LLM proposal 上优于 RSEA-style”的论文结论，也不支持对自由形式 prompt/tool/memory/workflow 修改的泛化主张。

下一轮应建立独立的 v3 proposal track，而不是修改或重跑已封存的 v2。v3 的首要目标是提升编译器对等价、自然语言修复意图的覆盖，并在新的 scenario seeds 与新增 failure family 上重新预注册可执行率和可靠/不可靠候选数量门槛。只有该门槛通过后，才将其作为进入 Qwen confirmation track 的依据。

## 7. 封存状态

`PILOT_SEAL.json` 已记录 `OLLAMA_FREEZE.json`、online protocol、30 条候选账本、candidate-level 决策、多轮轨迹、offline hidden labels 与全部报告的 SHA-256。此后不得依据本轮隐藏结果修改并重跑 v2；任何协议或编译器改动必须作为新的独立 track 记录。
