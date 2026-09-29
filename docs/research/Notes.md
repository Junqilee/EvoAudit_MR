**论文**：Recursive Self-Evolving Agents via Held-Out Selection

RSEA 的固定 held-out selection 可以概括为：

固定一个验证集 (D_v)，**整个 evolution 过程中 (D_v) 不更新、不重采样**。每一代先在 evolve set (D_e) 上生成轨迹并得到候选状态 (\tilde{s}_g)，再始终用同一个 (D_v) 评估其性能。

更新有两层规则：

* **Working state (s)**：如果候选在 (D_v) 上的得分不低于当前状态，
  [
  v(\tilde{s}_g)\ge v(s),
  ]
  就接受候选作为下一代状态。允许“持平更新”，用于在 plateau 上继续探索。

* **Best state (s^\star)**：只有候选严格优于历史最好成绩，
  [
  v(\tilde{s}_g)>v^\star,
  ]
  才更新 (s^\star)。最终测试只使用这个 frozen best state。

因此核心就是：

[
\boxed{\text{固定 }D_v + \text{当前状态用 }\ge\text{ 更新} + \text{最佳状态用 }>\text{ 更新}}
]

若所有候选都没有严格超过初始 vanilla ReAct，则最终返回空 state，等价于 vanilla ReAct。






**论文**：EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems

EvoTest 的核心是：**LLM 权重始终冻结，测试时学习发生在 episode 之间，而不是通过梯度更新。** 每个 episode 内使用固定配置
[
\chi^{(e)}=(p^{(e)},M^{(e)},h^{(e)},u^{(e)}),
]
episode 结束后，Evolver 根据完整轨迹 (\tau^{(e)}) 同时修改这四类组件，生成下一轮候选配置。([arXiv][1])

具体而言：

| 组件                        | 测试时如何修改                                                                                                                                                                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Prompt (p)**            | Evolver **直接重写整个 guiding/policy prompt**。从成功轨迹中提炼精确的有效动作，形成 `Walkthrough / Essential Actions`；从失败和循环中提炼 `Actions to Avoid` guardrails；若尚未完成任务，再加入 `Exploration Plan`。因此 prompt 会逐 episode 从简单原则逐渐变成较具体的行动策略。([arXiv][1])                   |
| **Memory (M)**            | episode 后程序化解析 transcript，把**导致正向 score increment 的 state-action pair** 写入 success memory，例如 `(state hash → successful action, score delta)`；下一 episode 遇到相同状态时检索该 action，并以 hint 的形式注入 Actor prompt。([arXiv][1])                          |
| **Tool-use routines (u)** | Evolver 会修改两类逻辑：① **state extractor**：生成/改写 `extract_state(game_history)` Python 函数，通过游戏输出中的关键字符串识别 milestones，把长历史压缩为当前状态摘要；② **memory interaction logic**：改变何时、以多强的约束使用 memory，例如从“可以查 memory”逐渐变成“每一步都必须先查 success memory”。([arXiv][1]) |
| **Hyperparameters (h)**   | Evolver 根据上一 episode 的行为动态调整推理参数，论文最具体实现的是 **temperature**：如果 agent 陷入循环或过于保守，则提高 temperature 增加探索；如果行为过于随机、偏离已有计划，则降低 temperature；表现已经合理则保持不变。([arXiv][1])                                                                                |

这里有一个值得注意的细节：正文把 memory 描述成包含 **success memory + failure memory**；但 Appendix J 的具体实现进一步说明，失败行为（如“在 hallway 中执行 west 没有任何变化”）**并不一定作为可查询数据库条目保存**，而是主要被转化为 prompt 中的 `Known Dead Ends / Actions to Avoid` guardrail。换言之，实际实现更接近：

[
\boxed{
\text{success experience}\rightarrow M
}
]

[
\boxed{
\text{failure experience}\rightarrow p\ \text{中的负向规则}
}
]

([arXiv][1])

最后，**不是所有修改后的配置都直接继承到下一 episode**。Evolver 生成多个 child configurations，连同上一轮 parent 一起进入候选池，再利用 UCB 根据“历史平均性能 + exploration bonus”选择一个 (\chi^{(e+1)})。被选中的配置在整个下一 episode 中保持固定；episode 完成后才再次 evolution。([arXiv][1])

因此，EvoTest 可以非常简洁地概括成：

[
\boxed{
\text{Play}
\rightarrow
\text{Analyze transcript}
\rightarrow
{\text{rewrite prompt, update memory, tune }h,\text{ rewrite tools}}
\rightarrow
\text{UCB select}
\rightarrow
\text{Play again}
}
]

它与前面 RSEA 最大的区别之一是：**RSEA 主要通过固定 held-out validation 做 state selection；EvoTest 则是在同一测试任务的连续 episodes 中直接用此前 test-time experience 演化整个 agent configuration，并通过 UCB 进行在线 exploration–exploitation selection。** ([arXiv][2])

[1]: https://arxiv.org/pdf/2510.13220 "EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems"
[2]: https://arxiv.org/abs/2510.13220?utm_source=chatgpt.com "EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems"


