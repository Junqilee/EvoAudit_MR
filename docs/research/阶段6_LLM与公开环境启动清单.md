# 阶段 6：LLM Proposal 与公开环境验证启动清单

## 当前结论

受控主实验与独立 OOD challenge 已完成并封存；下一批证据必须来自真实 LLM proposal 和作者未构造的公开环境。当前本机没有可用 GPU，项目虚拟环境中也尚未安装 LLM 推理栈或公开环境依赖，因此本文件只冻结启动条件与实验契约，不把未运行的 Track 记为结果。

## Track A：LLM proposal

### 目标

将候选来源从程序化 catalogue 替换为冻结 LLM 根据可见 trace 产生的 prompt、memory、tool 或 workflow patch，检验 EvoAudit-MR 的完整“proposal → audit → commit/reject → persistence”链路。

### 在开始前一次性冻结

| 字段 | 冻结内容 |
| --- | --- |
| 主 proposal model | 一个 7B–8B instruction model 的精确 repository revision 与 tokenizer revision |
| 第二模型 | 不同系列的 7B–8B instruction model；只做小规模方向复验 |
| 推理 | inference backend、量化、GPU/API 版本、temperature、top-p、max tokens、随机种子 |
| proposal schema | `patch_type`、before/after、rationale、证据 trace id；只允许 prompt/memory/tool/workflow 四种结构化 patch |
| 重复规则 | 每个 `(environment, seed, round)` 固定一次 proposal；invalid/no-op 计入结果，绝不重抽 |
| 审计 | 沿用 Stage-4 冻结 MR 与预算；新的 LLM Track 单独 HMAC 封存 hidden test，不能使用 Stage-4 与 OOD hidden labels 调参 |

### 最小可投稿配置

- 主模型：AliasTool 与 PermissionPath，3 个 shared seeds，8 rounds，4 个 gate。
- 第二模型：同两环境，2 个 seeds，8 rounds，仅检验方向一致性。
- 每个 run 记录 proposal 原文、结构化 patch、parser 结果、invalid/no-op、各 gate 的审计证书、commit rate、每轮成本、final test、replay retention 与安全指标。

### 启动所需资源

- 一张可运行 7B–8B 推理模型的 GPU，或经批准的模型 API；
- 对应模型权重/API 凭据；
- 本地独立虚拟环境与可下载依赖的网络访问。

## Track B：公开环境验证

### 选择

首选对齐目标是 SEAGym：其论文明确保存 train、frozen update-validation、test、replay、cost 与 snapshot 记录，正好对应本文的终局能力、历史能力和审计成本报告。但截至当前检索，只确认到论文，未确认一个可直接复现的公开代码仓库，因此不能把它列为已接入的环境。[SEAGym paper](https://arxiv.org/abs/2606.17546)

可立即尝试的实现备选是 AgentGym 的 **WebShop** 或 **ALFWorld** 子环境。AgentGym 是开源统一 agent-environment 接口，提供 ReAct 轨迹、环境 reset/step 接口和多种交互环境；其中 WebShop 和 ALFWorld 的任务规模相对适合先做轻量外部验证。远端版本已解析为 commit `3ef9235d23e68e7c2920c5422ad957dc8ced5c6c`，首次完整克隆在当前命令时间上限内未完成，残留目录已清理；因此尚未形成可运行的本地 checkout。[AgentGym repository](https://github.com/WooooDyy/AgentGym)

### 外部验证协议

1. 克隆并固定 AgentGym commit，优先选择一个子环境；先跑通 base agent 的 10 个任务 smoke test。
2. 构造仅影响 harness 的候选 patch（先 prompt/memory，随后可扩展 tool policy），由 Track A 的冻结 proposal model 生成。
3. 将公开任务切为 evolution / fixed validation / final test / replay 四个互不重叠的集合，并保存任务 id、snapshot、随机种子和完整轨迹。
4. 比较 Direct、RSEA-style、fixed random audit 和 EvoAudit-MR；每个 gate 接收相同 proposal 和总 rollout 预算。
5. 报告 final test performance、replay retention、round curve、commit rate、无效候选比例、更新成本和审计成本。环境若没有可执行安全 oracle，则安全性只作为“不足以报告”的边界，不能伪造为候选级安全结论。

### 当前阻塞

本机预检未发现 `torch`、`transformers`、`vllm`、`llama_cpp`、`huggingface_hub` 或 `agentenv`，且 `nvidia-smi` 不可用。远端版本预检已经成功；当前限制是完整源码下载未在命令时间上限内完成，而不是论文或环境接口不可用。获得 GPU/API 与允许下载依赖的环境后，再执行首次安装和 base-agent smoke test。
