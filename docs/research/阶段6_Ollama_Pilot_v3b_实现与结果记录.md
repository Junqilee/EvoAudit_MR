# 阶段 6：Ollama LLM Proposal Pilot V3b 实现与结果记录

## 结论

V3b 完成并已封存。它修复了 V3 的“模型输出契约与严格 parser 不兼容”问题：本地 `qwen2.5:7b` 在 6 个预封存公开兼容性任务上 6/6 通过 schema、证据引用和 compiler materialization；随后在冻结配置下完成 30 个真实 LLM proposal slots、五个系统的在线决策和离线评测。

本轨可以支持的结论是：在**受限 typed-policy 更新族**中，patch-conditioned EvoAudit-MR 比 Direct、固定验证和等预算随机审计更少采纳 hidden-unreliable 的 LLM 提议，同时保留一部分 reliable 更新。它不能支持“任意自然语言 prompt/tool/workflow 修改均可被审计”，也不能用本轮终局表现声称 EvoAudit-MR 已稳定优于 Direct/RSEA：六条持久演进轨迹的终局均值尚未拉开。

## V3 的永久封存

V3 保留原有 Gate A 成功结论，但其 freeze preflight 因模型生成了错误的 `claimed_scope` 而失败。它没有重试，未覆盖旧文件，也没有补造响应：

- Gate A：passed；
- freeze preflight：failed；
- proposal calls：0；
- online decisions：0；
- method comparison：unavailable。

终止记录见 [V3_TERMINATION_SEAL.json](evoaudit_mr/artifacts_llm/ollama_pilot_v3/V3_TERMINATION_SEAL.json)。

## V3b 实现

模型只生成以下五个字段：`claimed_target`、`policy_delta`、`natural_language_instruction`、`rationale`、`evidence_trace_ids`。`patch_type` 与 `claimed_scope` 改由系统按照环境注入：AliasTool 为 `tool_adapter`，PermissionPath 为 `workflow`。`policy_delta` 仍只允许公开 policy space 中的 1--3 个不重复 assignment；未知字段、非法值、冲突组合和 no-op 均 fail-closed 且不重抽。

Ollama 改为调用原生 `/api/chat`。每个环境各有一份 JSON Schema，同时出现在 `format` 与 prompt 中；采样参数固定为 `temperature=0`，响应文本与 SHA-256 会被记录，随后才通过严格 parser 和 compiler。

新增的关键实现文件：

- `evoaudit_mr/src/evoaudit_mr/llm/ollama_native.py`：原生 schema-constrained Ollama client；
- `evoaudit_mr/src/evoaudit_mr/llm/v3b_ir.py`：简化的模型输出 IR 与逐环境 JSON Schema；
- `evoaudit_mr/src/evoaudit_mr/llm/ollama_pilot_v3b_protocol.py`：独立 V3b seal、source lock 与 phase lock；
- `evoaudit_mr/src/evoaudit_mr/runners/ollama_pilot_v3b.py`：A1/A2、冻结、在线、离线完整协议；
- `evoaudit_mr/src/evoaudit_mr/llm/ollama_pilot_v3b_offline.py`：post-lock hidden labels 与终局考试；
- `evoaudit_mr/configs/ollama_pilot_v3b_manifest.json`：冻结的公开调度与 source hashes。

## 协议与封存

| 步骤 | 状态 | 证据 |
|---|---:|---|
| A1：公开 compiler readiness | 通过 | 23 assignment/router/behavior cases，132 个合法组合，12 个冲突组合拒绝 |
| A2：6 个公开 schema compatibility cases | 通过，6/6 | 两环境均覆盖；均为合法 JSON、可 materialize、证据 ID 可见 |
| 冻结 | 完成 | Ollama 0.32.9；`qwen2.5:7b` digest `845dbda0...` |
| 线上 proposal stream | 完成 | 30 slots；每 slot 一次生成；共享外生 stream |
| online phase lock | 完成 | 120 条动态决策 + 30 条 Static 记录 |
| 离线 hidden 评测与 final seal | 完成 | Gate B/C 均按预注册规则通过 |

完整封存包位于 [artifacts_llm/ollama_pilot_v3b](evoaudit_mr/artifacts_llm/ollama_pilot_v3b)，最终清单为 [PILOT_V3B_SEAL.json](evoaudit_mr/artifacts_llm/ollama_pilot_v3b/PILOT_V3B_SEAL.json)。

## 候选质量：Gate B

30 个 slots 中 24 个可执行，6 个是 behavioral no-op；AliasTool 为 9/15 可执行、PermissionPath 为 15/15 可执行。因此候选充分性通过：可执行数不少于 18、两个环境均至少 6 个、存在可靠与不可靠候选、至少四种 delta/hidden-behavior signatures，且固定/随机强基线确实出现 false acceptance。

以**唯一 canonical candidate**为统计单位，24 个可执行候选中有 3 个 hidden-reliable、21 个 hidden-unreliable，且 15 个不可靠候选满足可见目标改善条件。这是应在论文中使用的候选级计数。

注意：封存的 `reports/gate_b.json` 中 `canonical_reliable=12`、`canonical_unreliable=84` 是同一 canonical event 被四个 method 的 canonical decision 记录重复计数的产物；对应的去重值分别为 3 和 21。该重复不改变 Gate B 的任何通过/失败判断（可靠候选仍恰为预注册下限 3），但论文统计和后续正式 Track 的 Gate B 实现必须以 `event_id` 去重，不能直接引用这两个原始计数。

## 候选级方法比较

以下指标在 24 个可执行、**method-specific parent** 的决策事件上计算；`UUR` 为 reliable updates 的保留率。它们说明本轨存在实质性的审计机制差异，但样本很小，不应报告显著性结论。

| 方法 | 接受可靠更新 / 30 slots | 接受不可靠更新 / 30 slots | FAR | FDR | UUR | 安全违例接受比例 |
|---|---:|---:|---:|---:|---:|---:|
| Direct | 0 | 6 | 0.250 | 1.000 | N/A | 1.000 |
| RSEA-style fixed validation | 0 | 6 | 0.250 | 1.000 | N/A | 1.000 |
| Fixed random audit | 1 | 4 | 0.174 | 0.800 | 1.000 | 0.800 |
| EvoAudit-MR | 3 | 3 | **0.143** | **0.500** | **1.000** | **0.500** |

这满足 Gate C 的机制层判断：EvoAudit-MR 不是全拒，保留了 reliable updates，并相对至少一个强基线减少 false acceptance。原始表见 [candidate_metrics.json](evoaudit_mr/artifacts_llm/ollama_pilot_v3b/reports/candidate_metrics.json)。

## 多轮终局结果与边界

统计单位是 2 个环境 × 3 个 seeds = 6 条 trajectory；不是 120 条独立样本。所有方法都在相同的 30-slot proposal stream 上运行，但第一轮后各自在其 own parent 上重新 materialize、审计和得到 hidden label。

| 方法 | Overall | Target | Replay | Safety success | Unsafe-probe rate |
|---|---:|---:|---:|---:|---:|
| Static | 0.167 | 0.000 | 0.000 | 0.500 | 0.500 |
| Direct | 0.667 | 0.500 | 1.000 | 0.500 | 0.500 |
| RSEA-style | 0.667 | 0.500 | 1.000 | 0.500 | 0.500 |
| Fixed random audit | 0.611 | 0.500 | 0.833 | 0.500 | 0.500 |
| EvoAudit-MR | 0.667 | 0.500 | 1.000 | 0.500 | 0.500 |

因此，本轨的可靠表述是“候选采纳机制优势得到支持，长期终局优势在该小样本 stream 中未观察到”。尤其不能写成“EvoAudit-MR 在所有终局指标上优于 RSEA/Direct”。详见 [final_metrics.json](evoaudit_mr/artifacts_llm/ollama_pilot_v3b/reports/final_metrics.json)。

## 验证

新增 2 个 V3b 单元测试（模型不能提供系统字段；完整 mock 协议 A1→A2→30-slot→offline），并运行全量测试：**50/50 passed**。

## 下一步

V3b 不再修改、不重跑。它的后续用途是作为“本地 7B + constrained LLM-proposed updates”的封存证据。正式 Qwen Track 应使用新的 scenario seeds 和新的组合 failure family，并在其 Gate B 中修正 canonical candidate 去重；同时应继续推进 OOD challenge 和公开环境验证，以补足外部有效性与多轮长期收益证据。
