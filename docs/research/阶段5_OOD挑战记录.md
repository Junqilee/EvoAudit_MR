# 阶段 5：独立 OOD Challenge 记录

## 目的

这是一项在 Stage-4 主实验封存后新建并独立锁定的 **post-primary OOD challenge**。它检验已经冻结的 EvoAudit-MR，面对主实验中未出现的更新失效家族时，能否继续识别不可靠更新；它不是为主实验补充更多同分布样本，也不用于重新设计 MR。

## 协议与封存边界

- 主实验 `formal-v1-final2` 与 `multiround-v1-final2` 保持封存，不修改其 MR、阈值、候选或结果。
- OOD Track 使用新的 HMAC hidden seed、独立 manifest 和独立 online/offline 两阶段锁定；它是结果揭示前锁定的独立实验，但不是主实验开始前预注册的一部分。
- OOD 候选由 3 个环境、每环境 8 个未见机制家族、每家族 3 个参数实例构成，共 72 个事件；统计上的机制单位是 **24 个机制家族**，不是 72 个独立机制。
- 在线 gate 只看到候选 patch、可见任务和原有冻结 MR；hidden oracle 在 online lock 后才揭示可靠性。OOD 结果出来后不再据此修改 MR。

运行产物位于 `evoaudit_mr/artifacts_ood/ood-challenge-v1/`：`ONLINE_COMPLETE.json`、online certificates、`offline_hidden/events.jsonl`、`candidate_ood_offline.csv`、`ood_main.csv` 和按未见机制家族拆分的结果表。

## OOD 候选构成

该集合包含真正修复、可由原 MR 捕获的 target/safety failures、以及只在新的 hidden target 或 hidden safety profile 才暴露的 failures。后两类故意不在主实验 MR 的设计样本中，以检验“MR library 覆盖不足”这一真实边界。

## 结果

| 方法 | TP | FP | TN | FN | FAR | FDR | UUR | SVR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct commit | 18 | 54 | 0 | 0 | 1.000 | 0.750 | 1.000 | 0.458 |
| Fixed held-out | 18 | 45 | 9 | 0 | 0.833 | 0.714 | 1.000 | 0.476 |
| Fixed random audit | 18 | 27 | 27 | 0 | 0.500 | 0.600 | 1.000 | 0.400 |
| EvoAudit-MR | 18 | 27 | 27 | 0 | 0.500 | 0.600 | 1.000 | 0.400 |

这里的 `SVR` 沿用候选级 oracle 的安全事件密度定义；它不是多轮评估中已修正的 `unsafe_probe_rate`。

## 如实解释

1. OOD 结果支持一个较窄但重要的结论：冻结的 patch-conditioned 审计仍优于固定 held-out 验证（FAR 从 0.833 降至 0.500）。
2. 它**不**支持“EvoAudit-MR 在 OOD 上优于随机审计”：二者在本次冻结运行中相同。
3. EvoAudit-MR 漏掉了 27/54 个不可靠更新，集中于三类只在新的 hidden target/safety profile 中显现的失效。这说明 MR 的覆盖范围是方法的决定性边界，而非可以由一次主实验的完美分类掩盖。
4. 因为 EvoAudit-MR 是一个冻结的规则式采纳机制、不是通过机制家族训练的分类器，本实验是“未见机制家族 cold-start”检验，而不是有训练/测试折叠的字面 leave-one-family-out 学习实验；论文不得将其表述为后者。

## 论文中的定位

主文将把该结果用作 limitations 与 failure analysis：EvoAudit-MR 的核心价值是以 update-specific probes 减少固定验证的盲区，而不是自动发现所有未知失效模式。后续若扩展 MR library，必须建立新的、再次独立封存的 challenge set 来评估，不能复用本 OOD 结果作为调参反馈。
