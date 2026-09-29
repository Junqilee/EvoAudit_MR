# 阶段 6：LLM 接入与 SEAGym 部署记录

## 本次完成内容

### 1. 冻结式 LLM proposal 接入

已在 `evoaudit_mr` 实现 LLM candidate proposal 的最小可复现实验链路：

1. 从**可见 trace**构造 prompt；LLM 只能返回 `prompt_strategy`、`memory_skill`、`tool_adapter` 或 `workflow` 四类结构化 patch。
2. 严格校验 JSON schema、证据 trace 是否可见、scope 是否与 patch type 一致；任何 invalid/no-op 都记录并继续，绝不为获得“好候选”而重抽。
3. 将结构化 patch 编译为当前三个受控环境中可执行的 patch，并在冻结前检查编译是否成功。
4. 以一次真实 API 调用生成不可覆盖的 `LLM_FREEZE.json`；其中只保存公开配置、请求/响应/patch 的哈希、模型实际返回名和 token 计数，不保存 API key 或原始响应。

实现位置：

- `evoaudit_mr/src/evoaudit_mr/llm/`
- `evoaudit_mr/src/evoaudit_mr/runners/llm_preflight.py`
- `evoaudit_mr/configs/llm_proposal_v1_qwen.json`
- `evoaudit_mr/configs/llm_proposal_v1_deepseek.json`

这里的 LLM 负责生成候选更新；EvoAudit-MR 的 six-pair audit、online/offline 隔离和 hidden oracle 均保持不变。当前 compact harness 的执行器采用受限 DSL，因此这一步可严谨地支持“真实 LLM 产生候选、由审计机制采纳或拒绝”，但不能宣称已经覆盖任意自由形式代码修改。后续公开环境 Track 将把同一接口接入真正的 prompt/memory/workflow 修改。

### 2. API key 环境变量

已为下列**用户级环境变量**写入占位值，等待人工用真实 key 覆盖：

- `EVOAUDIT_QWEN_API_KEY`
- `EVOAUDIT_DEEPSEEK_API_KEY`

项目从不在 JSON 配置、日志或 freeze 文件中保存 key。推荐在新的 PowerShell 中运行下列命令并按安全提示输入（不要把 key 发到聊天中）：

```powershell
cd 'C:\01 work\15 智能体自演进\evoaudit_mr'
.\scripts\configure_llm_api_keys.ps1 -Provider qwen
.\scripts\configure_llm_api_keys.ps1 -Provider deepseek
```

填写后，先做无 API 调用的配置校验：

```powershell
& .\.venv\Scripts\python.exe -m evoaudit_mr.runners.llm_preflight --config configs\llm_proposal_v1_qwen.json --mode validate
```

确认输出无误后，再执行一次实际冻结调用：

```powershell
& .\.venv\Scripts\python.exe -m evoaudit_mr.runners.llm_preflight --config configs\llm_proposal_v1_qwen.json --mode freeze --output artifacts_llm\qwen_v1\LLM_FREEZE.json
```

### 3. 本地验证

- `python -m unittest discover -s tests -v`：42/42 通过。
- Qwen 与 DeepSeek 配置均通过无网络、无计费的 `--mode validate`。
- 本次没有向任何 LLM API 发起请求。

## 公开环境选择与部署

### 选择：SEAGym 作为第一个公开环境

SEAGym 是本项目的第一选择，原因不是 GitHub star 数，而是它原生定义了 self-evolution 所需的 lifecycle：train、frozen update-validation、test、replay、cost 和 snapshot。这样可直接承载本文的“proposal → audit → commit/reject → persistence”协议，避免我们先在 AgentGym 上自行拼装切分和状态持久化，再难以说明实验协议是否公平。

AgentGym 仍应作为第二个、更加任务多样的 transfer environment。它有更多环境和更高社区可见度，但它的环境安装、外部服务、数据与子模块依赖更重，且其通用 reset/step 接口没有直接提供本文所需的 frozen validation/replay/commit 生命周期；在当前无 GPU、希望快速取得可解释外部证据的约束下，不适合先做。

### 已部署的 SEAGym

- 目录：`evoaudit_mr/external/SEAGym`
- 固定 revision：`9e61e14db1f1355de944cd7c5b10c244fc74e82d`
- 安装方式：使用 EvoAudit-MR 的 `.venv` 进行 editable install。
- 已跑通：`examples/deterministic/config.json` 的 inspect、runtime check 与静态 baseline train。
- smoke run 输出：`evoaudit_mr/external/SEAGym/results/runs/evoaudit_public_smoke_seagym_v1/`。

该 smoke run 证明本机能执行 SEAGym 的真实 split/lifecycle 和 artifact 管理；它使用的是仓库自带确定性基线，**不是**本文的外部有效性结果，也不应写入论文主表。

SEAGym 全仓库测试在 Windows 上有 4 个失败、2 个错误：包含符号链接路径差异与需外部 E2B/runtime 配置的测试。确定性示例的关键路径已通过；运行论文级的 TerminalBench/HLE 配置前，仍需按 SEAGym 文档配置 E2B、任务资源以及 API 预算。

## 紧接着的执行顺序

1. 由人工填写 Qwen key，完成 Qwen 的一次 preflight + freeze；冻结后不再改模型、采样参数、proposal schema 与 invalid 规则。
2. 以冻结 Qwen 在 AliasTool 和 PermissionPath 做小规模 LLM proposal pilot；如实记录 valid/invalid/no-op、commit rate、six-pair audit 成本和终局测试。
3. 配置 E2B 后，在 SEAGym 的公开任务上复用同一采纳协议，报告 final test、replay retention、commit rate、成本和多轮曲线。
4. 待 SEAGym 外部结果稳定后，再选择 AgentGym 的一个任务（优先 WebShop 或 ALFWorld）作 transfer 验证，而不是同时展开 14 个环境。
