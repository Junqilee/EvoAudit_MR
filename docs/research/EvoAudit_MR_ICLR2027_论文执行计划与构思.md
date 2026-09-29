# EvoAudit-MR：面向可靠自演进智能体的变形回归审计

> 版本：2026-08-11  
> 目标：ICLR 2027 主会（摘要 2026-09-11 AOE；全文 2026-09-16 AOE）  
> 工作定位：冻结基础模型、无 RL 微调；研究“每一次自演进更新是否值得被采纳”，而非再提出一种更会生成 prompt 的 Evolver。

---

## 0. 先给结论：保留 EvoAudit，但必须收紧创新点

原始的 “为自演进增加 held-out validation / safety gate” 已不新：RSEA 已用独立留出集，只保留不退化的自然语言状态更新；SEAGym 已提供 train/update-validation/ID-OOD/replay 的评测视图；EvoPolicyGym 也以隐藏验证集选择最终 checkpoint。因此，本项目**不能**把“有留出集”写成核心贡献。

本文的可投稿版本应改为：

> **EvoAudit-MR 在每次 agent 更新前，针对该更新的声明作用域，自动构造可执行、语义不变的变形反事实测试（metamorphic counterfactual probes）；并以成对、序贯、受预算约束的审计同时验证：目标提升、非目标能力不退化、以及安全不变量不被破坏。只有获得可复查的 update certificate 的更新才会被提交。**

一句话类比：RSEA 像让员工在另一套题上考试，EvoAudit-MR 则像针对“这次改的是收银流程”专门设计盲测：换商品名、换排队顺序、制造无关干扰、检查是否误扣款，并确认后厨流程没有被误伤。

### 0.1 审计对象：不是只审工具，而是审四类 agent 更新

本文将 agent 看作由冻结 LLM 加上一层可修改的 **harness** 组成。审计对象覆盖四类主要更新，而不是只研究工具：

| 更新对象 | 例子 | 典型风险 | 对应审计重点 |
|---|---|---|---|
| Prompt / 策略规则 | 新增“先检查再执行”的规则 | 对某个措辞或偶然模式过拟合，干扰原任务 | 实体别名、无关信息、反向任务族上的鲁棒性与回归 |
| 记忆 / 技能 | 写入“遇到状态 X 就做动作 A” | 把偶然相关当因果规律；旧经验被错误覆盖 | 状态/实体映射、规则翻转、历史经验 replay |
| 工具适配 | 改参数映射、重试规则、权限配置 | 字段顺序依赖、错误工具复用、越权副作用 | schema/顺序变形、未改工具回归、权限不变量 |
| 工作流 | 新增 verifier、改 planner-executor 路径 | 为提升局部任务跳过检查或破坏其他路径 | 路径组合、非目标任务 replay、不可逆动作确认 |

四类更新共用同一“候选提出 - 审计 - 提交/拒绝”接口，但每类更新调用不同的 MR（变形关系）与安全规格。本文的价值正是在统一接口下**按改动类型测试**，而不是把所有更新塞进同一组固定验证题。

### 0.2 本文到底创新什么、明确不创新什么

**不创新的部分**：

- 不提出 metamorphic testing 这一概念；它是软件测试中的成熟方法。
- 不声称自动发现任意领域、任意 agent 的全部变形关系。
- 不声称解决开放世界中所有安全问题，或给出“绝对安全”保证。

**拟提出的四项具体增量**：

1. **更新条件化的 MR 路由**：读取这次 patch 改了什么、声称修什么，再从经人工定义和环境 oracle 验证的 MR library 中挑选/实例化最相关的测试，而非固定随机抽题。
2. **作用域外回归审计**：除目标任务外，显式测试本次更新不应影响的组件、工具和历史技能；把“是否误伤”变为更新级指标。
3. **鲁棒性 - 保持 - 安全的联合采纳门**：MR 证据、历史能力 replay 和程序化安全不变量共同决定 commit；三者不是三套独立报告。
4. **预算化、可复查的更新证书**：在有限 rollout 下进行成对序贯检验，记录证据、阈值、成本、版本和决策；用 FAR/UUR 衡量选择器是否真的可靠。

这四项共同回答一个新问题：**当一个自演进 agent 刚提出一次具体更新时，在有限测试预算下，怎样决定它是否应进入长期状态？**

### 0.3 论文要证明的不是“绝对安全”

绝不能声称一次小规模实验保证开放世界安全。本文只做如下可证伪的、受限的主张：在有程序化 verifier 的测试时自演进设置中，EvoAudit-MR 相比无门控和固定 held-out selection，能以相同的候选生成器与总交互预算：

1. 更准确地拒绝**最终会在隐藏测试退化**的更新；
2. 保留更多真实有效的更新，或在相同可靠性下使用更少审计 rollout；
3. 降低指定安全不变量上的违规；
4. 使进化过程可审计，而不只是报告最终最高分。

### 0.4 当前的最大风险与应对

| 风险 | 事实 | 处理原则 |
|---|---|---|
| 新近重叠 | RSEA 已有 strict held-out keep-better gate。 | 它是**必做基线**，不是可略过的相关工作；本工作必须胜在 mutation-specific MR、作用域回归与预算化证据，而非“再做一次 holdout”。 |
| benchmark 重叠 | SEAGym、EvoPolicyGym 都在评测进化快照与隐藏验证。 | 不新建泛化的“又一个 self-evolution leaderboard”；只提供能测量 false acceptance 的小型诊断套件，并优先接入现有环境。 |
| 五周截止 | 从 8 月 11 日到全文截止约 36 天。 | 先做最小可证伪实验；两周内若不存在无门控误接收现象，停止 ICLR 冲刺并转为更长期项目。 |
| 方法被说成软件 CI | 的确与 regression testing 有相似性。 | 正面承认；贡献在于解决 LLM agent 自演进中“无无限独立测试集、更新作用域未知、环境随机、测试成本有限”的特有选择问题。 |

---

## 1. 拟题、摘要骨架与论文叙事

### 1.1 推荐标题

**EvoAudit-MR: Metamorphic Regression Testing for Reliable Test-Time Evolution of Language Agents**

备选：

- *Audit Before Adopt: Counterfactual Evidence Gating for Self-Evolving Language Agents*
- *When Should an Agent Keep Its Own Update? Scope-Aware Auditing for Test-Time Evolution*

不要用 “Safe Self-Evolving Agents” 或 “Provably Safe”：证据范围和理论保证都不足以支撑。

### 1.2 一段式摘要草案（实验结果处先用占位）

Language agents increasingly modify their prompts, memories, tool routines, and workflows after deployment. Existing systems generally retain updates based on visible trajectory reward or a fixed held-out split, leaving them vulnerable to update-specific shortcuts, latent regressions, and behavioral safety degradation. We formulate **reliable test-time evolution** as a selective update problem: an update should be adopted only when there is evidence of target improvement, preservation outside its intended scope, and satisfaction of executable safety invariants. We introduce EvoAudit-MR, a model-agnostic audit layer that converts an update proposal and its failure trace into scope-aware metamorphic probes, evaluates parent and candidate with paired sequential tests, and issues a replayable update certificate before commit. We further introduce [name] diagnostic suites containing known shortcut and regression mechanisms. Across [environments], [backbones], and [seeds], EvoAudit-MR reduces false update acceptance by [x] while preserving [y] of useful updates, improving hidden-transfer performance under matched interaction budgets. These results show that reliable self-evolution requires auditing **each update mechanism**, not merely selecting the highest visible score.

### 1.3 审稿人应该记住的三件事

1. **问题**：自演进的单位是 “update”；但多数论文只评最终分数，无法知道中间被采纳的更新是否真的好。
2. **方法**：不是再加一套固定验证题，而是基于更新和环境契约，生成语义不变的反事实回归探针，并对目标、非目标和安全三个维度发证。
3. **证据**：在相同预算下，普通 visible reward、随机留出、固定 held-out（RSEA-style）会错误采纳某些 shortcut 更新；EvoAudit-MR 可量化并减少这类 false acceptance。

---

## 2. 文献综述：研究脉络、贡献与对本文的精确缺口

### 2.1 反思、经验与测试时改进：能改，但“该不该保留”尚未成为一等问题

| 代表工作 | 做了什么 | 对 EvoAudit-MR 的启发 | 未覆盖的点 |
|---|---|---|---|
| ReAct (ICLR 2023) | 把 reasoning 与 action/tool 调用交替执行。 | 提供最小 agent 行为环。 | 固定 agent，无更新选择问题。 |
| Reflexion (NeurIPS 2023) | 把失败写成 verbal reflection，供后续尝试使用。 | 失败轨迹可生成候选改动。 | 反思通常直接注入上下文，未测试其是否伤害其他任务。 |
| Self-Refine (NeurIPS 2023) | 自反馈迭代改写当前输出。 | 强化 “generate - critique - revise” 模式。 | 多是单任务输出改写，不是跨 episode 提交更新。 |
| ExpeL (AAAI 2024) | 从成败轨迹抽取经验，检索复用。 | 更新对象可为经验/策略而非权重。 | 缺少对每条经验的回归与安全证据。 |
| Voyager (2023) | Minecraft 中自动课程和代码技能库。 | 技能/程序可积累且可执行验证。 | 不把错误技能提交看作可量化的 false acceptance。 |
| EvoTest (ICLR 2026) | 在 J-TTL 中每 episode 进化 prompt、memory、工具例程与超参。 | 最贴近的“无梯度、测试时整个系统进化”基线。 | 同一游戏多轮学习；并未把更新特异的反事实回归审计作为选择机制。 |

**小结**：这一支解决 “如何从轨迹提出改变”，但通常把成功反馈直接当作留存依据。EvoAudit-MR 不与它们竞争候选生成能力；任何反思器、memory writer、workflow evolver 都可接入本审计层。

### 2.2 自动 agent 设计与代码自改写：提升了搜索能力，也扩大了错误提交面

| 代表工作 | 做了什么 | 相关但不同之处 |
|---|---|---|
| ADAS (ICLR 2025) | meta agent 在代码空间中设计新 agent。 | 关注新 agent 的发现，不定义每个变更的可靠性证据。 |
| AFlow (ICLR 2025) | 用 MCTS 搜索代码表示的 workflow。 | 有执行反馈和树搜索，但本文研究的是候选 workflow 更新何时应提交。 |
| AgentSquare (ICLR 2025) | 在 planning/reasoning/tool/memory 模块空间重组。 | 模块化空间可作为 EvoAudit-MR 的 typed mutation interface。 |
| Darwin Gödel Machine (2025) | 维护 archive，生成并评估自改代码的 coding agents。 | 已有实证验证和跨基准转移；但不是面向任意 test-time update 的作用域化 MR 协议或 false-accept 指标。 |
| HyperAgents (2026) | task agent 与 meta agent 同一可编辑代码库，自改“改进机制”本身。 | Docker 隔离解决代码执行层风险；不等于行为正确性、能力保持和工具安全的 update admission test。 |

**必须公平表述**：DGM 并非“没有验证”，它也报告 held-out transfer；HyperAgents 也在隔离容器中评估候选。本文的差别不在于首次验证候选，而在于把**更新接受决策**显式化为一个有反事实、保留与安全约束的选择问题，并按更新依赖关系生成最有诊断力的测试。

### 2.3 数据自由自演进与多智能体共演化：解决数据瓶颈，但可能放大 reward shortcut

| 代表工作 | 做了什么 | 和本文关系 |
|---|---|---|
| WebRL (ICLR 2025) | 从失败轨迹生成在线课程，以 RL 训练 web agent。 | 证明课程和反馈能带来跃迁，但训练成本高。 |
| Agent0 (2025) | curriculum agent 与 executor agent 通过多步、工具集成的协同竞争，无外部数据自演进。 | 自生成数据和工具轨迹可成为系统性 shortcut 来源。 |
| Search Self-Play (ICLR 2026) | proposer/solver 通过检索式自博弈共同提高。 | 通过外部资料保证答案，但题目效用与更新副作用仍需审计。 |
| CoMAS (ICLR 2026) | 以多智能体讨论动态产生内在奖励并进行 RL 共演化。 | 讨论奖励并不天然等于鲁棒效用；本文可在无 RL 的设置先研究可靠提交。 |

这类工作不适合作为当前主实验：RL、多 agent rollout 和搜索成本都会超过实习生五周的预算。但它们提供了重要动机：未来候选越多、修改越快，选择器/审计器越关键。

### 2.4 安全、保持与评测：与本文最接近，也最需要正面比较

| 工作 | 已解决问题 | 与 EvoAudit-MR 的边界 |
|---|---|---|
| **Your Agent May Misevolve** (ICLR 2026) | 系统展示 model/memory/tool/workflow 四条进化路径都可能造成安全退化或漏洞；讨论缓解方向。 | 关键动机和安全案例来源。它是风险实证与分析，不是一个针对每个候选更新的、可与性能共同优化的 admission 算法。 |
| **RSEA: Recursive Self-Evolving Agents via Held-Out Selection** (2026-06) | 将同一任务分布的 development pool 切为互斥的 evolve set `D_e` 与 validation set `D_v`：在 `D_e` 产生轨迹并重写三层自然语言状态，在 `D_v` 选择是否保留；最终 test split 不参与选择。 | **最强基线**。本文不能重复其“独立同分布留出能防一般过拟合”的结论。EvoAudit-MR 的可检验主张更窄：当固定 `D_v` 未覆盖某次 patch 的特有失效机制时，mutation-specific MR、作用域外回归与安全不变量可提供额外证据。 |
| **SEAGym** (2026-06) | 将 Harbor 任务转为动态 train/validation/test/replay/cost 视图，记录快照，诊断遗忘与 transfer。 | 可作为评测协议/后端；它不规定一个 update proposal 应如何自适应地产生并挑选 audit probes。 |
| **EvoPolicyGym** (2026-07) | 在 16 个交互 RL 环境中评估可执行 policy 的有限预算进化，隐藏验证选择 checkpoint。 | 提供“可见反馈 vs 隐藏选择”的强设置。本文不重做 leaderboards，而研究从 mutation 到 probe 的机制和行为安全不变量。 |
| AgenticEval (Findings ACL 2026) | 将 LLM 安全评估看作持续演化的 benchmark 构建。 | 它进化 evaluator；本文在 agent 自我修改时审计 update。 |
| ARMeta (2026) | 用多 agent 的 metamorphic relations 测 REST API。 | 采用 MR 的软件测试思想；对象是 API，不是自演进 agent 的更新选择、能力保持和安全。 |

### 2.5 本文必须引用、复现或明确讨论的最低文献集合

主文至少覆盖：Reflexion、ExpeL、ADAS、AFlow、EvoTest、DGM、HyperAgents、Agent0、CoMAS、Misevolution、RSEA、SEAGym、EvoPolicyGym。补充材料给出更完整的 survey 表。

**为什么 RSEA 是最强基线**：它已经抓住“不能用产生更新的任务来验收更新”这个本质，并对 `D_e` / `D_v` / final test 做了严格隔离。若候选只记住 `D_e` 的偶然规律，它通常会在未参与 rewrite 的、同类型 `D_v` 实例上退化；因此 RSEA 给出的是对**同分布泛化**的有价值统计证据。它不是绝对保证：`D_v` 有限，且可能未覆盖字段顺序、权限收紧、实体别名或跨组件副作用等特定触发条件。本文必须先实证这些条件确实存在，不能把它们假定为 RSEA 的既有失败。

**底线**：若 RSEA 的公开代码/论文细节表明它已经实现了动态变形测试、mutation-specific regression 与安全不变量，或实验发现固定 `D_v` 在匹配预算下已充分覆盖所有设计 trap，那么本题不应继续作为 ICLR 主线；应转向 ToolShiftBench 或与导师重新选题。

---

## 3. 精确定义：什么是“可靠的测试时自演进”？

### 3.1 设置

固定基础 LLM 为 `f`。agent 的可演进 harness 写成：

`A_c = (f, p, m, t, w, h)`

其中 `p` 为策略/系统指令，`m` 为结构化经验与检索规则，`t` 为工具适配器与权限声明，`w` 为规划/执行工作流，`h` 为可解释运行参数。一次 episode 产生轨迹 `τ` 和环境反馈 `r`。Evolver 从历史 `H` 提出结构化 mutation `u`，得到候选 `c' = Apply(c, u)`。

现有常见的提交规则近似为：

`commit(u) iff mean_reward(c', D_visible) >= mean_reward(c, D_visible)`。

问题在于 `D_visible` 同时产生了 mutation 的灵感和分数，且只观察到局部任务。本文定义更新的三类证据：

- **目标收益（target gain）**：在更新声称要修复的任务族 `T+` 上有所提升；
- **作用域外保持（non-target preservation）**：在应不受这次改动影响的 `T-` 上不退化；
- **安全保持（invariant preservation）**：在安全相关集合 `S` 上不违反程序化性质，例如权限、数据最小化和不可逆操作确认。

真正希望判断的是：

`Reliable(u) = [Δ(T+) > δ] ∧ [Δ(T-) ≥ -ε] ∧ [Pr(violate S) ≤ α]`。

这里不将它称为“因果证明”：MR 只能为有限环境给出更强的反事实证据。论文应诚实地称其为 **counterfactual-style / metamorphic evidence**。

### 3.2 RSEA 的 fixed held-out 与本文审计集的关系

为避免概念混淆，完整实验使用四类互斥数据/测试来源：

```text
D_e：evolve tasks
     产生失败轨迹，并触发候选更新；候选可以“看见”这些数据。

D_v：fixed held-out validation tasks（RSEA-style）
     与 D_e 属于同一任务分布、实例不同；只用于一般的同分布选择。

P(u)：update-conditioned audit probes（EvoAudit-MR）
     对某次具体 patch u，从 MR library、历史 replay 和安全规格中生成；
     包含 P+(目标鲁棒性)、P-(作用域外保持)、P_safe(安全)。

D_test：final hidden evaluation
     从未参与 update、MR 路由或阈值选择；仅用于论文最终报告和计算 FAR 真值。
```

`D_v` 与 `P(u)` 不是替代关系，而是互补关系。前者回答“这个新策略对同类但未见任务是否仍有用”；后者回答“这次改工具/记忆/工作流的方式，是否在它最容易犯错的变化下仍成立，且是否误伤不相关能力”。实际方法可保留小的 `D_v`，但本文的关键对比是：在**总测试预算相同**时，`D_v` 的随机/固定选择与 `P(u)` 的作用域化选择谁能更准确地区分好、坏更新。

### 3.3 为什么采纳门必须同时检查三类证据

三类检查不是武断的 checklist，而是一个受约束的工程优化目标：

| 证据 | 具体问题 | 若缺失会发生什么 |
|---|---|---|
| Target gain (`P+`) | 这次更新是否真的解决了它声称的问题？ | 最安全的策略是拒绝所有更新，系统不再自演进。 |
| Non-target preservation (`P-`) | 它是否为了修一个问题而伤害旧能力或未修改模块？ | 出现 context distraction、灾难性遗忘或跨工具回归。 |
| Safety invariants (`P_safe`) | 它是否通过越权、泄露、跳过确认等方式获得任务分数？ | 即使任务成功、旧能力也保持，行为仍不可部署。 |

因此采纳规则是最小三元组：既要有新收益，又不接受不可接受的性能回归，也不能违反明确的安全规格。这与自演进综述提出的性能保持（Excel）和安全适应（Endure）原则一致；本文把它们具体化为每一次 update 的可执行测试。它不是完整安全理论，覆盖范围只限于环境明确定义并可程序验证的不变量。

### 3.4 新的过程级指标

最终准确率不足以说明 Evolver 是否可靠。对有限、有 oracle 的 audit universe，在每一轮之后离线穷尽地计算候选的真实状态，定义：

- **False Acceptance Rate (FAR)**：被在线机制 commit、但在 hidden full audit 中不满足 `Reliable(u)` 的比例；
- **Useful Update Recall (UUR)**：hidden full audit 认定可靠的候选中，被 commit 的比例；
- **Acceptance Precision (AP)**：`1 - FAR`；
- **Regression Burden (RB)**：所有已提交版本相对父版本在 `T-` 上的负增益总和；
- **Safety Violation Rate (SVR)**：已提交版本违反任一不变量的概率；
- **Evidence Cost (EC)**：每一个真阳性 commit 的 rollout / token / wall-clock 成本；
- **Final hidden transfer**：最后版本与初始版本在从未被作过 update/audit 的任务上的差异。

FAR 是关键：有了可控 oracle 后，才可以直接测量“系统在更新时是否被骗”。

---

## 4. 方法构思：EvoAudit-MR

### 4.1 设计原则

1. **Evolver-agnostic**：候选可以来自 Reflexion、EvoTest、RSEA、AFlow-style workflow search 或人工模板；审计层不改变其生成机制。
2. **不依赖 LLM judge 作真值**：环境成败、权限和副作用由程序 verifier 判断；LLM 仅用于生成候选/解释，而非最终裁判。
3. **作用域显式化**：每个 mutation 必须声明自己改了哪个组件、打算修复哪类失败、允许影响哪些工具/任务标签。
4. **同预算比较**：所有基线共享 mutation generator、最大候选数、总 rollout/token 上限；不允许 EvoAudit 仅靠多花测试费取胜。
5. **fail closed but not freeze forever**：证据不足时状态为 `defer`，保留档案并允许日后补证，而非把未知误写为失败。

### 4.2 输入与输出

输入：父版本 `c`、候选 mutation `u`、失败轨迹 `τ`、环境契约 `K`、历史回放缓存 `R`、审计预算 `B`。

输出：`commit / reject / defer`，以及不可变的 **update certificate**：

```text
candidate_id, parent_id, mutation_type, claimed_scope,
target-probe results, non-target replay results, safety results,
paired effect estimates and confidence intervals,
budget consumed, decision, failure tags, random seeds, code/config hash
```

### 4.3 Step A：受限、可解释的 mutation interface

首版不允许自由执行任意 LLM 代码。将 mutation 限制成 schema-validated JSON patch：

- `policy_rule.add/edit/delete`：具体的决策或反思规则；
- `memory.write/revise/deprecate`：带适用条件和来源的经验；
- `tool_adapter.edit`：工具名、参数映射、重试/权限配置；
- `workflow.edge/add/remove`：规划、执行、检查节点的有向边；
- `runtime_param.edit`：最大重试、检索条数、温度等。

每条 mutation 附带 `claimed_scope={component, task_tags, tools, invariants}`。这既使 probe routing 可实现，也防止本项目被误解为纯 prompt tuning。

### 4.4 Step B：从 mutation 与失败轨迹生成审计探针

探针分为三个桶，每桶都应由环境的可执行语义保证，而非仅靠文本改写：

| 桶 | 问的问题 | Probe 例子 |
|---|---|---|
| `P+` 目标反事实 | 这次成功是否跨越了表面 shortcut？ | 保持目标与最优行动不变，替换实体名、打乱无关 observation、改变 API 返回字段顺序。 |
| `P-` 作用域外回归 | 为修工具 A 的改动会伤害工具 B 或旧技能吗？ | 由 component/tag 覆盖的 reservoir replay；反向任务族；未改工具的任务。 |
| `P_safe` 安全不变量 | 它是否以提升分数为代价越权/泄露/不可逆？ | 相同目标但权限收紧；诱人的不安全工具；需要确认的删除/退款路径。 |

变形关系必须写成 `precondition -> transformation -> oracle-preserving relation`，例如：

```text
MR-ToolOrder:
precondition: 两个检索结果对最终状态等价；
transform: 交换 JSON 字段/候选列表顺序；
relation: 合法动作与最终成功标签保持不变。

MR-EntityRename:
precondition: 环境内部有一一对应的 object-id 映射；
transform: 将可见名称替换为新别名；
relation: 通过映射后的 action 与终态 reward 保持不变。

MR-AuthorityTightening:
precondition: 任务可在 read-only 权限完成；
transform: 拒绝写权限、同时暴露高奖励但越权工具；
relation: agent 必须仍成功且不得调用越权工具。
```

这里采用的是软件测试中已有的标准构造逻辑：先由需求/环境契约提出必要关系（MR），再从一个 source case 生成 follow-up case，并检查多个执行结果是否满足关系。本文**不**声称发明 MR，也不让 LLM 无约束地创造安全规则。首版只实现 6--8 个经手工审查、由状态机 oracle 验证语义的 MR；所谓“自动”仅指根据 `claimed_scope`、依赖标签与历史失败，在已有 MR library 中选择并实例化测试。论文的新方法是把这种成熟测试思想放进 self-evolution 的 update admission loop，并和回归/安全证据做预算化联合决策。

### 4.5 Step C：按证据价值分配有限预算

固定 held-out 可能浪费预算在与改动无关的题上。首版采用一个朴素但可复现的 routing score，而不是训练复杂的 learned selector：

`score(q,u) = dependency_overlap(q,u) + shortcut_risk(q,u) + undercovered_family(q) + safety_priority(q)`。

每次选择最高分的候选 probe；对 parent/candidate 使用同一初始 state seed，温度设为 0 的主实验降低方差。每桶最少一条测试，之后依据序贯置信区间分配剩余预算。

若数据为成败变量，使用 paired difference 的 bootstrap CI 或 exact paired test；若为 return，使用配对 bootstrap。只在满足以下条件时 commit：

```text
LCB(ΔP+) > δ
LCB(ΔP-) >= -ε
UCB(SVR on P_safe) <= α
budget <= B
```

其中 `LCB/UCB` 为指定置信水平下界/上界。首版可用固定 90% CI；不要在实验中调阈值后再报告同一结果。阈值、probe 数和决策规则在主实验前冻结。

### 4.6 Step D：证书、档案与回滚

- `commit`：写入 append-only archive，并把 certificate 与 config hash 绑定；
- `reject`：存失败类型，如 `shortcut`, `non-target regression`, `safety violation`, `insufficient evidence`；
- `defer`：保存候选，未来在同类任务累积足够 probe 后再审；
- 后续版本若在 final hidden audit 退化，报告为 FAR，**不回填或删除**历史记录；
- 对 deployment-like 演示，只允许 commit 版本进入 canary；全部环境在 sandbox 中运行，无真实支付、文件删除或网络副作用。

### 4.7 算法伪代码

```text
for episode t = 1 ... T:
    τ_t, feedback_t = Run(A_c, visible_task_t)
    u = Evolver.propose(c, τ_t, feedback_t)           # 与所有基线共享
    c' = ApplySchemaValidatedPatch(c, u)
    probes = RouteMRProbes(u, τ_t, contract K, replay R, budget B)
    evidence = SequentialPairedEvaluate(parent=c, candidate=c', probes)
    decision = Gate(evidence, δ, ε, α)
    Archive(c, u, evidence, decision)
    if decision == commit:
        c = c'
    R = UpdateStratifiedReplay(R, τ_t, task_tags)
```

---

## 5. 实验设计：先做能推翻自己的小实验，再扩展

### 5.1 核心研究问题（RQ）与假设

| RQ | 可检验假设 | 最重要指标 |
|---|---|---|
| RQ1：无门控进化会不会错留更新？ | visible-reward / direct-reflection 会有明显 FAR，且最终 hidden transfer 可能下降。 | FAR、RB、hidden transfer |
| RQ2：固定 held-out 是否足够？ | RSEA-style i.i.d. holdout 会遗漏依赖于名称、顺序、权限或局部相关性的 shortcut。 | FAR 与 UUR 的 precision-recall |
| RQ3：MR 是否比随机审计更有效？ | 相同 rollout 预算下，scope-aware routing 的 AP 更高或 EC 更低。 | AP、EC、预算-可靠性曲线 |
| RQ4：安全门是否会让 agent 停止进步？ | 三桶门控在保持/提高 hidden success 的同时减少 SVR；不是仅靠拒绝所有更新。 | commit rate、UUR、SVR |
| RQ5：是否跨 evolver/backbone？ | 结论在两个冻结 backbone、至少两类 mutation 上保持方向一致。 | 分组效应、置信区间 |

### 5.2 三层环境策略

不要把全部赌在新 benchmark。按“诊断性 -> 现有性 -> 现实性”三层推进。

#### Track A：AuditTrap（必须自建，低成本且有全 oracle）

构建 3 个 Gym/TextWorld 风格的可执行模拟器，每个 80--120 个参数化实例。每个环境内置一个可控 shortcut，因此可以穷尽判定候选更新是否真的可靠。

1. **AliasTool**：库存/日历/文件查询任务；训练轨迹中工具名称或字段位置与正确动作偶然相关，隐藏审计做 object rename、字段顺序置换和 schema-preserving rewrite。
2. **SwitchRule**：文本规则规划；早期 episode 中颜色/位置与动作相关，后期或 audit 中打破相关性；检查 memory/policy 是否学到真正规则。
3. **PermissionPath**：同一目标有“慢但合规”和“快但越权”两条工具链；正常分数若只奖励成功会诱导捷径，安全 oracle 记录权限、确认和不可逆副作用。

每一项任务均有：状态机、gold goal、允许操作、MR generator、完整隐藏 audit universe。它不是为了刷排行榜，而是测量 FAR 的实验仪器。

三项环境与四类更新的覆盖必须在实验表中明确列出，避免把“工具风险”误写成全文结论：

| 环境 | Prompt / 策略 | 记忆 | 工具适配 | 工作流 | 主要可观测失败 |
|---|---:|---:|---:|---:|---|
| AliasTool | 可选 | 可选 | 主测试 | 可选 | 表面字段/顺序依赖、未改工具回归 |
| SwitchRule | 主测试 | 主测试 | - | 可选 | 偶然相关被写成规则、旧经验冲突 |
| PermissionPath | 可选 | 可选 | 主测试 | 主测试 | 跳过检查、权限/副作用违规 |

如果 Week 4 前没有至少一个**纯 prompt/记忆** mutation 和一个**纯工具/工作流** mutation 的正反例，实验不能声称方法适用于四类更新，只能诚实报告为“工具与记忆更新的原型”。

#### Track B：EvoTest/J-TTL 真实测试时适应（必须优先接入）

复用 EvoTest 的连续 episode 设置，先选 2--3 个 Jericho 游戏。该轨验证对已有 benchmark 的兼容性：EvoAudit-MR 不应破坏测试时学习曲线。只采用可保证语义的 observation alias、无关描述置换和历史 replay；不要把没有严格 oracle 的自然语言同义改写当作主结论。

#### Track C：工具安全外部验证（时间允许才做）

优先选择 `τ-bench` 的可回滚、沙箱化设置，或 Misevolution 仓库中可安全复现的 tool/workflow 子任务。目标不是复刻其全部攻击，而是在至少一个公开环境展示：审计层可与原有 agent harness 对接，且能阻止同类行为回归。

### 5.3 mutation generator：严格控制公平性

所有方法共享同一个 `Trace2Patch`：它读失败轨迹后，只能在第 4.3 节 JSON schema 内产生一个 patch。主实验每一轮**只产生一个候选**，避免“更多采样 = 更高成功率”的混淆。

候选类型按实验均衡：

- policy/reflection rule；
- memory add/revise；
- tool adapter retry/argument mapping；
- workflow routing/verification step。

对于 Track A，另实现 deterministic seeded mutations（故意含 shortcut 的错误补丁和真正规则补丁），以证明测到的是 gate 的选择能力而非某个 LLM 的写作能力。

### 5.4 必做基线

| 基线 | 目的 |
|---|---|
| Static ReAct / no evolution | 确定基础能力与安全基线。 |
| Reflexion / direct commit | “从失败立即写反思”的典型无门控。 |
| EvoTest-style full-system evolution | 贴近测试时全配置进化。使用同一 mutation schema 的公平重实现；若可用则直接调用官方代码。 |
| Random gate | 同样数量的 probe，但随机挑选；排除“多测几题”解释。 |
| Fixed held-out gate（RSEA-style） | 同预算、disjoint i.i.d. 验证；这是最关键的强基线。 |
| Safety-only gate | 有安全测试、无 MR/non-target preservation；分离安全收益。 |
| MR-only / no-scope routing | 测变形测试本身与 mutation-specific routing 的贡献。 |
| EvoAudit-MR | 完整方法。 |

不用把 DGM、HyperAgents、CoMAS 作为主表基线：它们的搜索空间、代码执行权限和算力规模不匹配。主文要明确说明这一不可比性；附录可提供“受限 patch”适配演示。

### 5.5 公平协议、统计与报告

- 两个冻结公开 7--8B backbone；建议 Qwen2.5-7B-Instruct 与 Llama-3.1-8B-Instruct。若本地没有 GPU，可走同版本推理服务；不进行参数更新。
- 每个 task family 至少 5 个独立 environment seeds；统计单位是 `(task instance, seed)`，不是把同一轨迹的每一步当独立样本。
- 主表报均值、95% paired bootstrap CI、所有 seed；成功率时补 McNemar/配对置换检验。
- 总 rollout/token 预算严格匹配；画出 `FAR - evidence cost` Pareto 曲线，而非只报最有利的一个预算点。
- 在实验前冻结：任务划分、MR library、阈值 `(δ, ε, α)`、随机种子、主指标、排除条件；任何事后新增环境只放 exploratory appendix。
- 不使用 LLM-as-a-judge 判真值；自动 verifier 和 event log 是唯一任务/安全裁判。

### 5.6 目标结果形态（不是承诺的数值）

最理想的一张主图应呈现：

```text
                低审计成本  ------------------------>  高审计成本
False acceptance
      高        Direct commit / random gate
      |                     fixed held-out
      |                                  EvoAudit-MR
      低
```

同时，EvoAudit-MR 的 useful update recall 不能接近零；否则它只是“拒绝一切”的安全过滤器。论文最低可接受的经验现象是：在至少两个 Track A trap 和一个外部环境中，无门控与固定 holdout 均出现可复现的误接收，而 EvoAudit-MR 以相近预算降低 FAR，且不显著低于 static agent 的隐藏成功率。

### 5.7 必做消融与反驳实验

1. **是多花预算造成的吗？** 与 random/fixed holdout 做总 rollout 完全相同的比较。
2. **是因为拒绝更多吗？** 报 commit rate、UUR，并做“匹配 commit 数”的阈值扫描。
3. **MR 真的比固定留出强吗？** 对所有方法使用相同数量、相同任务族的 verifier；仅改变 probe 的生成/路由。
4. **是否只是合成环境的文字技巧？** 至少一个 public environment；且 Track A 的变换发生在状态/工具 schema 层，而非只换 prompt 文案。
5. **是否依赖某个 Evolver/backbone？** 两个 backbone；至少 deterministic mutation 与 Trace2Patch 两种候选源。
6. **是否仅提高安全却伤害能力？** 同时报 target gain、non-target preservation、SVR 和 final transfer。
7. **阈值是否脆弱？** 对 `δ, ε, α` 和预算扫 3--4 个设置，给 Pareto 前沿。

---

## 6. 论文结构（9 页主文）

| 页数预算 | 内容 | 目标 |
|---|---|---|
| 0.75 页 | Introduction + 一个 concrete false-accept 例子 | 让读者立刻理解“高分更新也可能是错误提交”。 |
| 0.5 页 | Related work | 重点正面对比 RSEA、SEAGym、EvoPolicyGym、Misevolution。 |
| 1.0 页 | Problem formulation + process metrics | 定义 reliable update、FAR、UUR。 |
| 1.75 页 | EvoAudit-MR | 一张系统图 + 一段算法 + update certificate。 |
| 1.0 页 | AuditTrap + protocol | 说明为何可得到 hidden oracle。 |
| 2.0 页 | Main results | RQ1--RQ4 的主表/主图。 |
| 1.0 页 | Ablations + cost | 反驳 “就是 holdout / 就是多测”。 |
| 0.5 页 | Limitations, safety, reproducibility | 主动限定结论。 |
| 0.5 页 | Conclusion | 回到“audit before adopt”。 |

附录：所有 MR 定义、环境契约、prompt/config、完整 seed、候选与 certificate 样例、额外 backbone、风险案例、代码与许可说明。

### 6.1 论文图表清单

1. **Figure 1**：从 failure trace 到 patch、MR probes、证书、commit/reject 的流程图。
2. **Figure 2**：一个 AliasTool 或 PermissionPath 真实案例：visible 成功、fixed holdout 漏过、MR 抓到。
3. **Table 1**：主要 FAR/UUR/SVR/hidden transfer，对所有 baselines，预算匹配。
4. **Figure 3**：FAR 与 evidence cost Pareto。
5. **Table 2**：组件消融（no MR、no scope、no safety、no sequential）。
6. **Figure 4**：版本演进时间线与 certificate 的可视化。

---

## 7. 从今天到 ICLR 截止：压缩投稿计划

> 这不是完整八周研究计划，而是唯一可能赶上 2026-09-16 的 36 天冲刺。若第 2 周 go/no-go 失败，应停止仓促投稿，转入第 8 节的完整周期。

### 7.1 逐周日程与交付物

| 日期 | 目标 | 必须交付 | Go / No-go |
|---|---|---|---|
| 8/11--8/16 | 定义与复现 | 一页 problem spec；读完 RSEA/EvoTest/Misevolution/SEAGym；实现 Static、direct commit、fixed-heldout 三个选择器；锁定 mutation schema。 | 不能在 6 天内跑通单个 deterministic env，则缩为纯 AuditTrap。 |
| 8/17--8/23 | 现象发现 | AliasTool + PermissionPath 最小版；20--30 个 deterministic mutation；完整 hidden oracle；预注册主指标。 | **8/23 Gate 1**：若 direct commit / fixed holdout 没有可复现误接收，或 MR 没有额外诊断价值，停止 ICLR 主线。 |
| 8/24--8/30 | 方法落地 | scope routing、paired sequential gate、certificate；跑 1 个 backbone、3--5 seeds 的 pilot；确定主图雏形。 | **8/30 Gate 2**：若 FAR 降低仅来自近零 commit rate，必须改阈值或转为 benchmark/diagnostic paper。 |
| 8/31--9/05 | 主实验 | 完成 Track A 两环境 + J-TTL 一个环境；运行所有消融；开始写 Introduction/Method/Experiment。 | 主表必须预算匹配，所有失败 run 保留。 |
| 9/06--9/10 | 锁实验与摘要 | 第二 backbone 最小验证；导师预审；匿名仓库；摘要、标题、作者名单确定。 | **9/11 AOE 前提交真实摘要**；新增作者在此后不允许。 |
| 9/11--9/16 | 成文与复现 | 9 页 PDF、补充材料、代码运行说明、许可证、随机种子清单、最终 sanity run。 | 不为最后一天的单次结果重写结论；如证据不足，宁可不投。 |

### 7.2 每日节奏（实习生可执行）

- 上午：读一篇关键工作或实现一个单元；下午：跑小实验；晚上：把结果、成本、异常都写入 `experiment_log.md`。
- 每天提交可运行代码/配置，而不是只保存 notebook 输出。
- 每周至少一次与导师对齐：本周证据是否支持“MR 选择优于 heldout”这一唯一主张。
- 至少留 4 天给写作与独立复跑；ICLR 主文 9 页，临截止日不适合仍在构建环境。

---

## 8. 完整 8 周研究计划（若不以 9/16 为硬截止）

### Week 1：问题与复现

- 精读并做 1 页对比表：EvoTest、RSEA、Misevolution、SEAGym、EvoPolicyGym。
- 实现统一 `AgentConfig`、`Mutation`、`Decision`、`Certificate` 数据模型。
- 复现 direct commit 与 RSEA-style fixed heldout gate；写 10 个 deterministic unit tests。

**产出**：可运行最小 loop，和一份已确认的 novelty matrix。

### Week 2：构造可证伪环境

- 完成 AliasTool、SwitchRule、PermissionPath 的最小版；每个有 hidden full audit universe。
- 手工写 6--8 条 MR，并用 environment oracle 测它们确实保持语义。
- 预注册 split、阈值和主指标；生成故意好/坏 patch 集合做 gate 单元测试。

**产出**：Benchmark v0；若未能产生 false acceptance，及时换 trap，而非强行叙事。

### Week 3：EvoAudit-MR 核心算法

- 实现 scope tags、probe router、paired runner、序贯 CI、证书 archive。
- 跑一个 backbone 的 smoke test；检查 reject/defer/commit 都会出现。
- 完成 no-MR、random、fixed-heldout、safety-only 四个可比版本。

**产出**：Figure 1 与一个真实 certificate 示例。

### Week 4：主要诊断实验

- Track A 的 3 个环境、5 seeds、两种 mutation source。
- 画 FAR-UUR、FAR-cost、commit-rate 图；保留所有候选与决策。
- 根据盲点补 MR，但此后冻结库，新增规则只进入 exploratory 附录。

**产出**：核心主表初版；决定是否值得扩展。

### Week 5：外部环境与有效性

- 接入 EvoTest/J-TTL 两个游戏；完成轻量 semantic-preserving probes。
- 评估对原测试时性能是否有负影响；排查环境转换是否破坏语义。
- 若资源允许，接入 `τ-bench` 或 Misevolution 的一条 sandbox tool 路径。

**产出**：至少一个非自建环境结果和局限性说明。

### Week 6：泛化与消融

- 第二 backbone；预算、阈值、probe 选择策略 sweep。
- 匹配 commit rate 与匹配 rollout 的反驳实验。
- 让同学独立运行 1 个 setup，检查脚本/随机种子可复现。

**产出**：完整实验包、95% CI、失败案例库。

### Week 7：写作与 artifact

- 主文完整初稿；补充材料列出全部 MR 和每个 environment 的安全合约。
- 开源仓库清理密钥、加 LICENSE、README、`reproduce.sh`、config 文件。
- 导师/同门按 ICLR reviewer 角色做一轮 harsh review，尤其攻击 “只是 holdout”。

**产出**：匿名 9 页 PDF v1、reproducibility checklist。

### Week 8：验证与投稿准备

- 独立重新跑主表；冻结图表与 seed。
- 补关于 RSEA/SEAGym/EvoPolicyGym 的细粒度对比；写 limitations、societal impact。
- 压缩 9 页、检查双盲、上传 supplement。

**产出**：可投稿版本或高质量 arXiv/下一轮会议版本。

---

## 9. 工程拆解、资源估算与目录建议

### 9.1 最小代码模块

```text
evoaudit-mr/
  configs/                 # 所有预注册 YAML
  agents/
    base_agent.py
    trace2patch.py
    mutation_schema.py
  audit/
    probe_library.py
    scope_router.py
    paired_runner.py
    sequential_gate.py
    certificate.py
  environments/
    alias_tool/
    switch_rule/
    permission_path/
    adapters/jtt.py
  baselines/
    direct_commit.py
    fixed_holdout.py
    random_gate.py
    safety_only.py
  analysis/
    metrics.py
    plots.py
  tests/
  docs/
```

### 9.2 低算力资源预算

- 不训练、不反传、不跑 RL；主成本是 agent rollout。
- Pilot：`2 environments × 3 seeds × 8 rounds × <=4 audit rollouts`，约 200--500 episode。
- 完整 Track A：`3 × 5 × 10 × <=5`，约 750 个 parent/candidate test pairs；再乘每 episode 的工具/LLM steps。
- 目标上限：两 backbone 合计不超过 5--10 万次短 LLM 调用。先使用廉价、固定版本的 7--8B 推理端点；只在最后对一个更强模型做小规模验证。
- 所有 tool 与副作用在 Docker/本地模拟器内；禁止真实文件删除、购买、邮件、生产 API key。

### 9.3 实验日志最少字段

每一次候选（包括失败）记录：任务 ID、parent/candidate hash、patch 类型、可见分数、每个 probe 的状态/action/reward、MR ID、权限事件、决策、token/rollout/时间、随机 seed。没有这些，FAR 和 certificate 都不可复查。

---

## 10. 审稿风险预演：我们如何回答

### R1：“这不就是 RSEA 的 held-out selection？”

答：RSEA 是最重要的直接基线，其固定 disjoint holdout 对自然语言状态进化有效。EvoAudit-MR 在相同 held-out 数量/预算下额外利用更新类型和环境契约产生 MR，并显式验证非目标回归与程序化安全不变量。主实验直接构造 RSEA-style gate 会漏过、MR 能抓到的 shortcut；若没有这个现象，本文不声称新颖性。

### R2：“这不就是软件测试/CI？”

答：是受其启发的可靠性层，但 agent 的修改是由不确定的 LLM 根据部分轨迹提出，测试集无限且测试成本昂贵，更新还会影响 memory、tool、workflow 等非代码状态。本文研究的是有限 probe 下的 selective update decision，并提供 update-level FAR/UUR 和可执行环境。

### R3：“合成 benchmark 不代表真实 agent。”

答：合成套件的角色不是替代真实 benchmark，而是提供 `Reliable(u)` 的 hidden oracle，以测量现实 benchmark 无法直接观测的 false acceptance。主结论需至少在 J-TTL 或工具环境验证；文章对外部泛化保持克制。

### R4：“安全不变量太人为。”

答：安全从来依赖明确规格。我们只报告受定义权限、确认、最小副作用等可执行属性，不外推到通用 alignment；Misevolution 的 tool/workflow 风险说明这类属性是有意义的。

### R5：“审计成本抵消了进化收益。”

答：成本是主指标，不隐藏。使用固定预算和 Pareto 曲线；若固定 heldout 用同等预算达到相同性能，EvoAudit-MR 不成立。

---

## 11. Go / No-go 决策表

| 截点 | 必须看到的证据 | 决策 |
|---|---|---|
| Day 7 | 至少一个 trap 中 direct commit 有明显 FAR；完整 oracle 可工作。 | 否则不继续写方法。 |
| Day 14 | fixed holdout 漏掉部分 update-specific shortcut；MR 在相同预算有更高 AP 或更低 FAR。 | 否则改投 ToolShiftBench/长期 benchmark，不以 EvoAudit 主投。 |
| Day 21 | EvoAudit-MR 不依赖“拒绝全部”而有合理 UUR/commit rate；在第二任务族方向一致。 | 否则把结论降为诊断研究。 |
| Day 28 | 主表、三种关键消融、一个外部环境已经完成。 | 否则不提交 ICLR 2027 主会。 |

这张表保护你的时间。研究失败不是失败；在错误的 novelty 上投入到 9 月 16 日才是失败。

---

## 12. 参考文献与开源起点

以下是开题/主文必须核对的第一手材料；会随阅读笔记补全作者、页码和 BibTeX。

1. Fang et al. *A Comprehensive Survey of Self-Evolving AI Agents* (2025). [arXiv:2508.07407](https://arxiv.org/abs/2508.07407)；项目：[EvoAgentX](https://github.com/EvoAgentX/EvoAgentX)。
2. Shinn et al. *Reflexion: Language Agents with Verbal Reinforcement Learning* (NeurIPS 2023). [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)。
3. Zhao et al. *ExpeL: LLM Agents Are Experiential Learners* (AAAI 2024). [arXiv:2308.10144](https://arxiv.org/abs/2308.10144)。
4. Wang et al. *Voyager: An Open-Ended Embodied Agent with Large Language Models* (2023). [arXiv:2305.16291](https://arxiv.org/abs/2305.16291)。
5. Hu, Lu, and Clune. *Automated Design of Agentic Systems* (ICLR 2025). [arXiv:2408.08435](https://arxiv.org/abs/2408.08435)。
6. Zhang et al. *AFlow: Automating Agentic Workflow Generation* (ICLR 2025). [arXiv:2410.10762](https://arxiv.org/abs/2410.10762)。
7. Zhang et al. *Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents* (2025). [arXiv:2505.22954](https://arxiv.org/abs/2505.22954)。
8. Zhang et al. *HyperAgents: Self-Referential Self-Improving Agents* (2026). [arXiv:2603.19461](https://arxiv.org/abs/2603.19461)；[code](https://github.com/facebookresearch/hyperagents)。
9. He et al. *EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems* (ICLR 2026). [arXiv:2510.13220](https://arxiv.org/abs/2510.13220)；[code](https://github.com/yf-he/EvoTest)。
10. Xia et al. *Agent0: Unleashing Self-Evolving Agents from Zero Data via Tool-Integrated Reasoning* (2025). [arXiv:2511.16043](https://arxiv.org/abs/2511.16043)；[code](https://github.com/aiming-lab/Agent0)。
11. Xue et al. *CoMAS: Co-Evolving Multi-Agent Systems via Interaction Rewards* (ICLR 2026). [arXiv:2510.08529](https://arxiv.org/abs/2510.08529)。
12. Shao et al. *Your Agent May Misevolve: Emergent Risks in Self-evolving LLM Agents* (ICLR 2026). [arXiv:2509.26354](https://arxiv.org/abs/2509.26354)；[code](https://github.com/ShaoShuai0605/Misevolution)。
13. Nguyen et al. *Recursive Self-Evolving Agents via Held-Out Selection* (2026). [arXiv:2606.28374](https://arxiv.org/abs/2606.28374)。
14. Zheng et al. *SEAGym: An Evaluation Environment for Self-Evolving LLM Agents* (2026). [arXiv:2606.17546](https://arxiv.org/abs/2606.17546)。
15. Wang et al. *EvoPolicyGym: Evaluating Autonomous Policy Evolution in Interactive Environments* (2026). [arXiv:2607.02440](https://arxiv.org/abs/2607.02440)。
16. *AgenticEval: Toward Agentic and Self-Evolving Safety Evaluation of Large Language Models* (Findings ACL 2026). [ACL Anthology](https://aclanthology.org/2026.findings-acl.727/)。
17. *ARMeta: Multi-Agent LLM-based Metamorphic Testing for REST APIs* (2026). [arXiv:2605.28321](https://arxiv.org/abs/2605.28321)。

### 建议阅读顺序（总计约 3 天）

1. RSEA：逐段拆 its state、split、keep-better 和所有 baseline；这是 novelty 校准。
2. EvoTest：拆清 actor/evolver/config space/J-TTL 协议；这是最贴近工程基线。
3. Misevolution：只读四条风险路径和实验设置；这是安全 task 设计来源。
4. SEAGym 与 EvoPolicyGym：吸收 visibility boundary、snapshot、replay、budget accounting，不重复造轮子。
5. DGM/HyperAgents：理解 archive/patch/sandbox，作为更自由 self-modification 的动机和局限性。

---

## 13. 第一周的实际行动清单

- [ ] 与导师确认：目标是冲 ICLR 2027 还是接受“8 周完整版本投下一轮”的风险偏好。
- [ ] 阅读 RSEA 全文并填一张 4 列表：state、selection、metrics、与 EvoAudit-MR 差异；任何相同点都不能自欺欺人。
- [ ] clone / 阅读 EvoTest、Misevolution、HyperAgents 的公开代码；只先跑/读最小路径，不尝试完整复现 HyperAgents。
- [ ] 建立上述目录，写 `mutation_schema.py`、`certificate.py` 和一个 AliasTool toy task。
- [ ] 制造至少 10 个已知好/坏 patch；先测试 gate 是否在没有 LLM 的情况下可区分它们。
- [ ] 在 8 月 16 日前给导师看一页 “novelty matrix + 第一张 FAR 示意图”。

这一步完成之前，不要花时间调 prompt、扩环境或追逐大模型分数。
