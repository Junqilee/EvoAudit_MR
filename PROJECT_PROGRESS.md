# EvoAudit-MR 项目阶段性进展

更新时间：2026-09-29

## 1. 项目目标

本项目面向“智能体自演进”中的更新采纳问题：当 agent 生成一个新的 prompt、记忆、工具适配器或工作流 patch 时，系统如何判断它是否值得保留。

核心方法是 EvoAudit-MR（patch-conditioned metamorphic auditing）：审计问题不再只检查固定验证集是否变好，而是根据本次 patch 的作用范围构造变形测试，同时检查三件事：

1. 目标能力是否改善；
2. 原有能力和 replay 能力是否退化；
3. 安全约束是否被破坏。

目标投稿：ICLR 2027。当前代码仍是受控环境研究原型，不应表述为已经解决任意真实 LLM agent 的更新采纳。

## 2. 已完成工作

### 阶段 3：EvoAudit-MR 原型

- 完成 `AliasTool`、`SwitchRule`、`PermissionPath` 等受控环境与统一 patch 接口。
- 完成 Direct、RSEA-style、Random Audit、EvoAudit-MR 的比较流程。
- 完成 online/offline 隔离、hidden oracle、HMAC commitment、certificate 和 phase lock。
- 完成单元测试与 mock 全流程测试。

### 阶段 4：受控正式实验

- 完成候选级和多轮持久演进 runner。
- 完成统计修正：full-universe matched thinning、`unsafe_probe_rate`、`safety_event_density`，并明确 candidate、method-parent event 和 trajectory 三类统计单位。
- 受控结果支持以下机制性结论：patch-conditioned MR 能发现固定验证集漏掉的 update-specific failure；但这不是对任意真实 agent 的普适性证明。

### OOD 与 LLM proposal track

- 完成独立 OOD challenge 协议，包含新 failure families、HMAC commitment 与 offline evaluation。
- Ollama V3/V3b track 已记录：V3 的接口兼容性失败被永久封存；V3b 的结构化输出和 compiler 流程已跑通，但本地 7B proposal diversity 有限。
- Qwen track 已完成：
  - A1 compiler/accounting readiness；
  - A2 六个 public schema compatibility cases；
  - 60 个 proposal slots 的 online/offline 闭环；
  - unique canonical labels 与 method-parent labels 的独立记账。
- 最新 Qwen 运行结果：45/60 个候选可执行，但预注册 Gate B 未通过（两个环境没有同时覆盖足够的 reliable/unreliable candidates）。因此当前 Qwen 结果只能作为 proposal-interface limitation 和实验边界，不能作为方法优越性的正式外部有效性证据。

## 3. 当前最重要的结论

当前最可信的论文主张是：

> 在受控、程序化的 agent 更新机制中，patch-conditioned metamorphic auditing 能识别固定 validation 漏掉的 update-specific regression，并在固定审计预算下改善更新采纳的安全性。

当前不能主张：

> EvoAudit-MR 已经普遍解决真实 LLM agent 的任意自演进更新采纳。

原因是：受控环境机制数量仍有限；LLM proposal track 暴露了 proposal diversity 和环境覆盖不足；公开真实 agent 环境的部署与验证尚未完成。

## 4. 后续计划

1. 保留并引用当前 Qwen/Ollama 失败或 Gate B 未通过的记录，不覆盖原始 artifact。
2. 建立全新 independent Qwen track：使用新 trajectory/scenario seeds、至少一个新的组合 failure family，并在查看 hidden label 前重新封存 prompt、schema、compiler、MR、threshold 和预算。
3. 调整 proposal 充分性设计，而不是根据当前 hidden label 修改 EvoAudit-MR：提高环境间 balanced coverage，确保两个环境均有足量 reliable 与 unreliable executable candidates。
4. 至少完成一个公开环境验证，报告 final performance、replay retention、multi-round curve、commit rate 和 audit cost。
5. 完成结果图表、统计单位说明、附录环境规范与 MR 列表，然后撰写 ICLR 2027 全文。

## 5. 在另一台电脑上的推荐启动顺序

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

如需调用 Qwen 或 DeepSeek，先在本机配置环境变量；不要把 API key 写入配置文件或提交到 GitHub。实验生成目录被 `.gitignore` 排除，需要时按 README 中的命令重新生成。
