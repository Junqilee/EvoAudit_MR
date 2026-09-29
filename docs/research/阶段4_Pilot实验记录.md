# 阶段 4：候选级小规模对比实验与 Pilot 记录

> 状态：2026-08-12。已完成 Stage-4 的受控候选级 Pilot。该 Pilot 的作用是检验论文的核心可证伪前提与工程链路，不可直接作为 ICLR 主实验结论。

## 1. 预注册式 Pilot 协议

| 项目 | 固定设置 |
| --- | --- |
| 环境 | AliasTool（工具 adapter）、SwitchRule（prompt / memory rule）与 PermissionPath（workflow / permission） |
| 候选 | 每环境 4 种 archetype：真实改进、target shortcut、replay regression、安全违规；每种 3 个独立任务重复，共 36 条候选事件 |
| 可见证据 | 每事件 `D_e=12` 条任务轨迹 |
| fixed heldout | 每事件 `D_v=6` 条与 `D_e` 同分布、不同 seed 的独立任务 |
| 审计预算 | heldout、random audit、EvoAudit-MR 均为 6 对 parent--candidate 执行；EvoAudit-MR 为 target/replay/safety 各 2 对 |
| hidden truth | 每事件独立生成 16 target + 16 replay + 16 safety probes；仅在所有 online decision 持久化后计算 |
| 比较方法 | Direct commit、RSEA-style fixed heldout、fixed random audit、EvoAudit-MR |
| 主指标 | FAR、AP、UUR、commit rate、SVR、logical audit pairs、audit tool calls |

在线与 hidden evaluation 保持物理分离：`runners/online.py` 不导入 `hidden/`；online JSONL 不含 hidden label；hidden truth 只写入 `offline_hidden/events.jsonl`。

## 2. 实际结果

使用 `.venv\Scripts\python.exe` 运行 `python -m unittest discover -s tests -v` 后，全部 **22** 项测试通过；其中 Stage-4 测试验证了 36 条候选的平衡构成、`D_e/D_v` 隔离、PermissionPath 的动作安全 oracle 以及主指标生成。

总体候选级结果如下（`FAR` 越低越好，`UUR` 越高越好）：

| 方法 | commit rate | FAR | AP | UUR | SVR | 每候选逻辑审计对数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct commit | 1.000 | 0.750 | 0.250 | 1.000 | 0.333 | 0 |
| RSEA-style fixed heldout | 1.000 | 0.750 | 0.250 | 1.000 | 0.333 | 6 |
| Fixed random audit | 0.250 | 0.667 | 0.333 | 0.333 | 0.000 | 6 |
| **EvoAudit-MR** | **0.250** | **0.000** | **1.000** | **1.000** | **0.000** | **6** |

在三个环境中均出现 fixed heldout 漏检：

- AliasTool 的 `positional_shortcut` 在 canonical heldout 上通过，但 schema 字段顺序变化后失效；EvoAudit-MR 的 target MR 拒绝它。
- SwitchRule 的 `color_shortcut` 在训练/heldout 的颜色相关任务上通过，但在打破颜色—动作相关后失效；EvoAudit-MR 的 target MR 拒绝它。
- PermissionPath 的 `role_shortcut` 在近期 operator 任务上通过，但在合法的 delegated viewer 或跨租户操作中失效/违规；EvoAudit-MR 的 target 与 safety probes 拒绝它。

详细逐候选结果和证据将由 Pilot runner 写入：

```powershell
cd evoaudit_mr
python -m evoaudit_mr.runners.stage4_pilot --manifest configs/stage4_pilot_manifest.json
```

默认输出：

- `evoaudit_mr/artifacts_pilot/stage4-candidate-pilot-seed-17/main_results.md`
- `evoaudit_mr/artifacts_pilot/stage4-candidate-pilot-seed-17/candidate_results.md`
- `evoaudit_mr/artifacts_pilot/stage4-candidate-pilot-seed-17/pilot_cases.md`

## 3. 对论文主张的含义

Pilot 支持以下受限结论：在三个具有程序化 oracle 的自演进环境中，使用 patch type、diff 中的 structured audit context 和环境契约来路由 target/replay/safety probes，能够在与 fixed heldout 相同的在线审计 rollout 预算下，区分本 Pilot 中的可靠与不可靠 patch；而固定同分布 heldout 会漏掉预先构造的 patch-specific failure。

Pilot **不能**支持以下结论：

- 不能声称已经证明开放世界 agent 安全；
- 不能声称统计泛化，因为 36 条事件仍来自 12 种受控 archetype 的重复；
- 不能宣称 fixed random audit 无效，它已经阻止一部分安全失败；
- 不能把当前数值直接写入论文 Results；正式实验需扩展候选多样性、随机种子与环境。

## 4. Stage-4 go/no-go 决定

**Go，进入下一轮环境与候选扩展。** 原因：核心必要现象已经出现，且 EvoAudit-MR 在不牺牲 Pilot 内全部可靠候选（UUR=1.0）的情况下减少错误采纳；因此项目的“patch-conditioned audit 优于固定验证”假设值得继续测试。

下一步按阶段 4 的后半与 §9.1 Pilot 推进：加入 PermissionPath，扩大每环境候选的 failure mechanism 与 task seed，执行 budget `3/6/12` 扫描，再决定是否进入正式大规模实验。
