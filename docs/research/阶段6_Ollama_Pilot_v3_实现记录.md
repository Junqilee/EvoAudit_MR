# 阶段 6：Ollama Pilot v3 实现记录

**状态：Gate A 已通过并封存；模型冻结预检失败，V3 online 未启动。**

## 1. 方案审查结论

V3 的总体设计合理：它将 V2 的自然语言关键词编译替换为 typed policy IR，并用 Gate A/B/C 将“编译可执行性”“候选区分压力”“方法机制证据”明确分开。该设计的结论边界保持为：EvoAudit-MR 审计的是受限 typed policy IR 中的 LLM-proposed update，而非任意自由形式 agent 修改。

实现时将完整 typed policy 放入每个 checkpoint；共享 delta 会分别相对于各方法自己的 parent materialize，因此 `label(method_parent, patch)` 在多轮演进中仍有严格定义。

## 2. 已实现内容

- `v3_ir.py`：严格 schema、typed delta、组合约束、公共 policy space 与 prompt 构造；
- `v3_compiler.py`：将同一 delta 分别 materialize 到 canonical / method-specific parent；
- `v3_executor.py`：AliasTool 与 PermissionPath 的确定性 typed-policy 执行器；
- `ollama_pilot_v3_protocol.py`：readiness seal、HMAC commitment、input seal、online phase lock 和最终 seal；
- `ollama_pilot_v3_offline.py`：仅 offline 导入的 parent-conditioned hidden labels 与 `D_final`；
- `ollama_pilot_v3.py`：readiness / freeze / online / offline / seal runner；
- `ollama_pilot_v3_manifest.json` 与 `ollama_pilot_v3_offline.json`；
- V3 单元、mock 全链路和全项目回归。

全项目回归结果：**48/48 passed**。

## 3. Gate A 实际结果

Gate A 真实执行并封存于：

`evoaudit_mr/artifacts_llm/ollama_pilot_v3/COMPILER_READINESS_SEAL.json`

结果：

| 项目 | 结果 |
| --- | ---: |
| 公共 typed assignment 执行 / router cases | 23 / 23 |
| 合法完整 policy combinations | 132 / 132 |
| 明确冲突 combinations | 12 / 12，均拒绝 |
| V2 public-only 无歧义 reference cases | 2 / 2 |
| V2 public-only ambiguous cases | 28 / 28，均不强制映射 |

Gate A 使用的 V2 输入仅来自 `candidate_ledger_online.jsonl` 的 online-public 字段；没有读取 V2 的 hidden label、offline task、hidden seed 或 gate outcome。

## 4. 冻结预检结果

在 Gate A 后，按 V3 计划进行了**唯一一次**本地 `qwen2.5:7b` freeze preflight call。该输出未通过严格的 typed IR parser：

```text
V3IRValidationError: claimed_scope must exactly match the environment contract.
```

因此：

- `OLLAMA_FREEZE.json` 未创建；
- `HIDDEN_COMMITMENT.json` 和 `ONLINE_INPUT_SEAL.json` 未创建；
- 没有发起 30 个 proposal slots；
- 没有 online/offline 结果可解释；
- 同一 V3 track 不进行 retry，也不修改 prompt/schema/compiler 后重跑。

## 5. 后续决策点

若继续，应新建独立的 **V3b protocol**：保留已封存的 Gate A 和本次失败记录不变，在新的 run ID 下针对本地模型的 schema-following 能力调整 public schema/prompt，并重新执行 readiness、freeze、HMAC、input seal 和 online phase。它不能覆盖或重写 V3。
