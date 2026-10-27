# ShopPilot 设计说明

## 1. 项目概述

**项目名称：** ShopPilot：面向多轮电商任务的搜索计划与工具轨迹优化 Agent

**目标：** 在隔离的零售任务环境中，研究显式搜索计划、记忆/约束状态和轨迹级奖励能否提高多轮 Agent 的任务完成率与工具使用质量，并形成可复现的数据集、基线、消融和失败分析。

项目针对 JD 中的多轮对话、search plan、电商 skill、个性化记忆、训练数据构造、Agentic RL、奖励设计和线下验证。交付重点是任务环境、可验证奖励和实验结果，不是新增一个泛用聊天入口。

## 2. 当前基础与改造边界

所有实现只允许发生在 `F:/longchain/实习项目/mypaperweb copy`。原 `mypaperweb` 和三个参考仓库均为只读参考。副本当前已有未提交改动；实现时要保留它们，只新增 ShopPilot 专属模块和测试，不格式化或重写无关文件。

副本已有可复用能力：

- `app/agents/research_workflow_service.py`：LangGraph 研究流程、澄清、计划、工具调用、judge、循环预算和 checkpoint。可作为多轮图编排的代码范式，不直接复用研究节点或其业务状态。
- `app/context/builder.py`：Gather、Select、Structure、Compress、Assemble 上下文管线，可在集成阶段通过 adapter 读取会话历史和记忆。
- `app/services/run_trace_service.py`：本地持久化 run/span、输入输出、耗时和失败状态，可记录实验轨迹。
- `app/evaluation/runner.py`、`types.py`、`metrics.py`、`failure_classifier.py`：现有单轮评测协议可借鉴；多轮任务优先由 ShopPilot 专属 runner 负责，避免把原评测结构改成电商领域模型。
- `app/services/memory/`、Skill registry 和 tool guard：可在后续集成阶段复用记忆/Skill/工具约束能力，但第一版实验环境要能离线独立运行。

不修改现有主应用路由、通用 Agent、ContextBuilder、Trace schema、数据库迁移或前端。首期通过独立命令行和 JSONL 产物运行。若之后要接入 UI/API，单独评审范围。

## 3. 参考仓库分析与采用决定

### tau-bench

本地 Retail 代码把任务环境抽象为 `reset(task_index)` 和 `step(action)`，任务包括用户指令、目标状态变更和预期输出，工具受 Retail 规则限制；结束时通过环境数据最终状态和回答输出计算奖励。这适合作为 ShopPilot 的环境和任务格式参考。已下载的 `tau-bench` README 明确提示该仓库的 Retail/Airline 任务版本过时，并建议使用 `tau2-bench`；因此本项目不把该仓库作为可直接依赖的最新基准，也不引用其排行榜分数作为自己的结果。ShopPilot 首期自行制作小型、确定性的中文零售任务集，并记录来源、许可证和任务模板。

### OpenRLHF

本地代码展示了统一的 `AgentExecutorBase`、交互式多轮执行、`reset`/`step` 环境反馈、自定义 agent function 和 reward function 接口，也提供 PPO/REINFORCE/GRPO 等算法及训练脚本。这支持将 ShopPilot 环境定义为算法无关接口，并让 RL adapter 在独立模块中实现。OpenRLHF 的脚本配置涉及 Ray、vLLM、DeepSpeed 和多 GPU；因此不是首期依赖。训练集群或 GPU 可用后，再通过兼容适配器提交多轮 rollout 和奖励。

### BrowserGym

BrowserGym 采用任务化环境、标准 observation/action 循环和独立 benchmark package，适合作为任务边界、任务拆分和运行器的参考。但其主要对象是浏览器/WebArena/视觉交互，需要 Playwright 和具体 benchmark 设置。ShopPilot 的研究变量是结构化电商工具调用与状态变更，不需要浏览器动作空间，所以不引入 BrowserGym 依赖，也不在首期跑其网页任务。

### MyPaperWeb 副本

现有图工作流、Trace、评测失败分类、上下文和 memory 代码提供了集成基础。ShopPilot 专属环境和指标需与现有评测分开，保持核心实验可本地复现，并避免将现有应用功能描述为新的算法贡献。

## 4. 研究问题与假设

**RQ1：** 对多轮零售任务显式抽取目标、约束、待澄清槽位、搜索计划和停止条件，是否比不使用计划减少漏约束和无效搜索？

**RQ2：** 基于环境最终状态的稀疏成功奖励，加入工具有效性、进度、重复调用、步数和答案依据等分项后，是否能改善候选轨迹排序或策略更新？

**RQ3：** 将用户偏好/任务约束存成有来源的短期状态，并按当前任务检索，是否提升跨轮约束满足率且不增加错误记忆注入？

假设：显式计划对多约束搜索、查询改写和缺信息澄清有帮助；结构化终局奖励比单独的文本关键词 judge 更可靠；过重的步骤惩罚会导致过早停止或少查证，必须与任务成功率联合评估。记忆仅作为独立消融，不将偏好召回率直接等价为推荐质量。

## 5. 范围

### 首期必须完成

1. 独立、确定性的 ShopEnv：`reset`、`step`、工具 schema、状态快照、动作日志和结构化终局奖励。
2. 中文零售工具任务：商品查询/详情/比较/推荐，以及订单查询、取消/退款等至少一个有状态变更且需要确认的业务流程。
3. SearchPlan schema：目标、硬约束、软偏好、缺失槽位、子目标、可用工具、停止条件与计划版本。
4. Agent adapter：将已有模型/Agent 接到 ShopEnv；保留原始 tool-calling baseline，并提供可插拔 planned Agent。受控环境不应依赖真实电商账户或外网。
5. 轨迹记录与奖励：拆分终局成功、约束、动作正确性、进度/效率和风险惩罚，输出每个分项以便审计。
6. 固定 train/dev/test 任务拆分、基准 runner、结果 JSON/Markdown、错误类别、重复运行统计和消融。
7. 轨迹导出 schema：将 `prompt/observation/action/tool result/reward/done/metadata` 导出为 JSONL，为后续 SFT/DPO/RL 准备数据，不声称已进行模型后训练。

### 后续扩展

- 有 GPU 时增加 OpenRLHF multi-turn Agent adapter、LoRA SFT 和 GRPO/REINFORCE 对照；训练前另做容量、硬件、模型许可和依赖版本核验。
- 接入真实 MyPaperWeb Memory、LangGraph 和 Trace 时，只通过 ShopPilot adapter，并确保租户/会话隔离；真实副作用必须继续受工具 guard/HITL 控制。
- 增加 online user simulator 或 τ²-bench 任务复现作为外部 sanity check，前提是版本、依赖、任务许可和评估口径先固定。

### 明确不做

- 不训练基座模型，不声称从头实现 GRPO/DAPO 或分布式训练基础设施。
- 不复制 tau-bench、OpenRLHF 或 BrowserGym 的源文件/数据集到本项目；先检查各自 license 和下载任务的使用条件，采用接口思想并保留来源链接。
- 不依赖真实商品/订单 API，不执行真实退款、下单或地址修改。
- 不做前端产品化，不改 MyPaperWeb 主路由和通用评测契约。
- 不以 LLM-as-judge 单一分数作为主要 reward 或唯一结论。

## 6. 组件设计

```text
Natural-language task
        |
        v
Intent / Constraint State ---- Memory adapter (optional, ablation)
        |
        v
SearchPlan planner
        |
        v
Agent policy (ReAct baseline | planned policy | learned/RL adapter)
        |
        v
Action validator -> ShopEnv.step -> deterministic tool observation/state
        |                                  |
        +------------ trajectory ---------+
                           |
                           v
                Reward evaluator + Trace
                           |
                           v
             fixed task runner / report / export
```

### ShopEnv

- `reset(task_id, seed) -> Observation`: 建立独立初始状态，返回用户消息、可见上下文、工具列表和 episode metadata。
- `step(action) -> StepResult`: 校验工具名和 JSON 参数，执行一个动作并返回 observation、状态变化、错误码、`done` 和可选 reward breakdown。基础 schema 校验始终存在；policy-level guard 是单独的实验变量，不能把环境拒绝非法 action 误记为 guard 策略收益。
- 环境状态与任务 gold state 分开；gold state 只由 reward evaluator 访问，不能泄漏给 Agent。
- 工具执行不调用网络。所有写操作在 episode 内存状态上执行，测试结束丢弃。
- `max_steps`、每工具超时和 tool allowlist 由 harness 强制；Agent 不能通过 prompt 修改策略约束。
- episode 有 `awaiting_confirmation` 状态。任务的 `user_turns` 依次提供初始请求、补充信息和确认回复；写操作在没有上一条规范化 affirmative confirmation 时返回 `confirmation_required`，不改变状态。Agent 先发 `respond` 请求确认，环境才推进到下一条确认回合；确认缺失或否定时保持状态并允许结束/改问。确认文本和状态转移都写入轨迹。

### SearchPlan 与 state

计划结构至少包含：`task_goal`、`hard_constraints`、`soft_preferences`、`known_slots`、`missing_slots`、`subgoals`、`candidate_tools`、`stop_condition`、`plan_status`。字段用 Pydantic 校验并带 schema version。每轮根据 observation 更新 plan，不将自然语言的自由形式 thought 作为结构化状态来源。

### Memory 条件

memory-on 只读取 task 明确提供的历史偏好记录，每条记录带 `memory_id`、`type`、`content`、`source_turn_id` 和 `created_at`；adapter 先按类型过滤，再按当前任务槽位做确定性的规范化匹配，最多注入 3 条，并在 plan/trajectory 中记录命中来源。memory-off 不注入任何历史偏好。两种条件使用同一 task、seed、policy 和 tool budget；Gold hard constraints、reference actions 和测试标签不能伪装成 memory。测试额外统计 expected memory hit、wrong injection、duplicate injection 和 memory-assisted constraint satisfaction，防止以错误记忆提升表面成功率。

### 奖励函数

每条 episode 保存分项，不只存一个总分：

```text
R_episode = w_s * success
          + w_c * constraint_satisfaction
          + w_a * valid_action_ratio
          + w_p * goal_progress
          + w_e * efficiency
          - w_r * repeated_call_ratio
          - w_u * unauthorized_or_unsafe_action
```

`success` 和硬约束由最终环境状态/任务验收器确定；`valid_action_ratio` 由工具 schema 和状态机确定；`goal_progress` 来自已完成子目标的差分；`efficiency` 只在成功 episode 内按必要动作数归一化；未经用户明确授权的写操作是硬失败/高额惩罚，不可由其他分项抵消。权重先在 dev 上确定并写入版本化 config，test 上冻结。LLM judge 只做诊断标签或抽样人工复核，不决定关键状态奖励。

分析时同时报告 success rate、hard constraint pass rate、正确工具/参数、澄清质量、步骤数、重复/无效调用、未授权写操作、延迟和 token/cost。不要让一个加权平均分掩盖安全硬失败。

## 7. 任务数据与防泄漏

初始数据固定为 90 条小型任务，覆盖 12 个独立任务族：`product_search`、`product_compare`、`recommendation`、`preference_memory`、`order_status`、`cancellation`、`refund_return`、`exchange`、`confirmation`、`tool_error_recovery`、`no_result_conflict`、`unsupported_request`。每个任务族生成 5 条 train、1 条 dev、1 条普通 test，共 60/12/12；另外生成 6 条跨族组合 stress test，最终为 train 60、dev 12、test 18。每个族的 `template_variant` 取值按固定规则分开：train 只使用 variant `v1-v3`，dev 使用 `v4`，普通 test 使用 `v5`；实体 ID、约束组合和语言表述也按 split 独立采样。每个 split 都覆盖基础能力，test 通过未见 variant、实体组合、约束组合和跨族流程测试组合泛化，不通过随机复制句子制造难度。

每个 task 至少有 `task_id`、`split`、`template_family`、`template_variant`、`user_turns`、`initial_state`、`memory_items`、`tools_allowed`、`policy_rules`、`goal_predicates`、`hard_constraints`、`reference_actions`、`expected_clarifications`、`confirmation_policy`、`seed`、`source/license`。`user_turns` 每项含 `role`、`message`、`turn_type`（`request|clarification|confirmation|negative_confirmation`）和可选 `expected_agent_action`；确认回合由环境按任务序列提供，不由 Agent 伪造。Gold state、reward labels 和 reference action 不进入 Agent observation。测试任务在算法/权重选择后冻结。

数据生成分为模板生成、实体填充、约束一致性校验、环境可达性校验、人工抽样、split 去重。LLM 可协助生成自然语言改写，但结构字段与动作可达性须由代码校验。保存原始 seed 和生成器版本，支持复现。

## 8. 基线、实验和验收

### Baselines

1. `D0`：无网络确定性直连启发式 policy；按关键词/槽位匹配选择第一个工具，不生成 SearchPlan，不做 policy-level guard。它保证没有 API key 时也能跑完整 MVP。
2. `B0`：可选的原始模型 ReAct/tool-calling，无显式计划、无 policy-level guard；如果没有模型配置则跳过并标记 optional。
3. `B1`：SearchPlan-only；使用计划排序子目标和候选动作，不增加 policy-level guard，环境基础 schema 校验仍保留。
4. `B1G`：SearchPlan + policy-level guard；单独衡量参数/权限/重复调用拦截收益。
5. `B2`：SearchPlan + fixed Reward-Aware Action Reranker（主方法）；候选生成、特征、pairwise 更新和 tie-break 规则固定在配置中。
6. `Ablations`：B2 去掉 progress、效率/重复项、软约束/grounding 项各跑一组；安全硬约束单独保留，不做去除后部署。

第一阶段无 GPU 时，B2 固定为**奖励感知动作重排器（Reward-Aware Action Reranker）**：policy 从确定性候选生成器产生最多 3 个结构化候选动作，重排器读取当前状态/计划/动作特征。pairwise 训练样本由 train split 上的固定策略 rollout 生成：在相同 episode state 克隆环境，分别执行候选动作并用相同后续 policy rollout 到终局；仅保留终局 reward 不同的动作对，reward 高的动作作 preferred label。纯 Python 线性 pairwise ranking 用这些样本更新并选择最高分动作，不调用外网或更新 LLM 参数。输入特征、候选生成规则、rollout 策略/seed、训练步数、学习率、初始化和 tie-break 规则写入 config；若 train rollouts 没有足够 reward 差异，报告“无有效 pair”，不得合成偏好标签。它的收益称为“离线策略/动作重排收益”，不能称为 GRPO 或基座模型训练效果。可选模型 adapter 只负责生成候选动作，不改变主方法定义。

### 统计口径

- 主指标：任务完成率（episode success rate）和硬约束满足率。
- 次指标：正确工具调用率、参数准确率、澄清必要性/充分性、平均步骤数、成功轨迹效率、重复调用率、无效调用率、越权写操作数、p50/p95 latency、token/cost。
- 对随机采样策略使用固定 seed，并按任务配对比较；报告置信区间或 bootstrap 区间及样本量。重复运行模型 Agent 时报告均值/方差，不只挑最好一次。
- 最低验收：环境状态隔离和终局奖励具有单测；任务 split 防泄漏测试通过；D0、B1、B1G、B2-off、B2-on 均可在同一固定 test 集运行；B0 在模型配置可用时作为 optional 对照运行；所有硬失败可从轨迹追溯；报告包含失败案例与分桶，不预设目标提升百分点。
- 若主方法没有提升，要定位分桶结果并报告负结果；不以调权重后同一 test 集重复挑选最优作为有效证据。

## 9. 可观测性、错误处理与安全

每条 trajectory 记录 task/version/seed、输入、plan 版本、action、参数、工具结果、状态 diff、reward breakdown、结束原因、延迟和模型/解码参数。trace 写入单独 `app/data/shopilot/`，数据导出时剔除密钥和个人信息。Agent/tool 错误分类至少区分 plan_parse_error、missing_constraint、unnecessary_search、wrong_tool、invalid_args、state_transition_error、premature_stop、repeat_call、unsafe_write、unsupported_claim、timeout。

未知工具/参数拒绝执行并返回稳定错误码。所有写操作先进入 `pending_confirmation`，只有 task 的确认回合满足验收后才允许状态变更。越权写动作不允许 retry 自动放行。LLM/API 超时标为 runtime failure，不伪装为零质量的正常轨迹。

## 10. 主要风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 模拟任务过于简单，策略只记模板 | 按模板族拆分，组合实体/约束，加入 OOD 改写和无答案任务 |
| Reward hacking，短轨迹高分但任务没完成 | 终局成功与硬约束设为门槛；效率奖励仅在成功时生效；审计逐项 reward |
| LLM judge 偏差 | 结构化环境状态为主要 oracle，judge 只做诊断并抽样复核 |
| 旧 tau-bench 任务/代码 | 明确版本过期提示；不复制测试结果；自己的环境先独立完成，外部 benchmark 只做后续对照 |
| GPU/训练环境不足 | MVP 保持 Python/本地模型或 API 无关；将 OpenRLHF 适配器放在可选 extra/脚本，不阻塞核心交付 |
| 当前副本存在未提交修改 | 新增文件限定在 `app/agent_algo/shopilot`、`scripts/shopilot_*`、`tests/test_shopilot_*`、`docs/superpowers`；逐文件检查 diff |
| 参考仓库许可不兼容 | 先记录 commit/version 与许可证；默认复用设计思想和协议，不复制代码或数据 |

## 11. 文件边界建议

首期新增：

```text
app/agent_algo/shopilot/
  __init__.py
  types.py                 # Action, Observation, Task, StepResult, EpisodeResult
  env.py                   # reset/step 和隔离状态
  tools.py                 # 零售工具 schema 与确定性实现
  task_loader.py           # task split 加载和 schema 校验
  plan_schema.py           # 结构化 SearchPlan
  planner.py               # 计划解析/更新 adapter
  policy.py                # ReAct/planned policy 接口与受限调用
  reward.py                 # 确定性终局验收与奖励分项
  trajectory.py            # episode 轨迹模型、JSONL 编解码
  runner.py                # 基准执行、复现 seed、聚合
  metrics.py               # ShopPilot 专属指标
  report.py                # JSON/Markdown 报告和失败桶
app/agent_algo/shopilot/data/
  tasks_train.jsonl
  tasks_dev.jsonl
  tasks_test.jsonl
  catalog.json
  orders.json
scripts/
  generate_shopilot_tasks.py
  run_shopilot_eval.py
  export_shopilot_trajectories.py
tests/
  test_shopilot_env.py
  test_shopilot_reward.py
  test_shopilot_data.py
  test_shopilot_runner.py
  test_shopilot_policy.py
docs/shopilot/               # 用户文档和实验报告，单独于本设计计划
```

若后续进入训练阶段，再另增 `openrlhf_adapter.py`、`train_sft.py`/`train_grpo.sh` 和训练配置，不能让首期核心模块导入 OpenRLHF、Ray、vLLM 或 DeepSpeed。

## 12. 参考来源

本机已下载代码为本次静态检查的首要参考：

- `F:/longchain/实习项目/tau-bench/README.md`、`tau_bench/envs/base.py`、`tau_bench/envs/retail/env.py`、`tau_bench/envs/retail/tasks_train.py`、`tau_bench/envs/retail/rules.py`。README 指出旧仓库任务过时，并链接 tau2-bench。论文引用：Yao et al., *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*, arXiv:2406.12045；Barres et al., *τ²-Bench: Evaluating Conversational Agents in a Dual-Control Environment*, arXiv:2506.07982。
- `F:/longchain/实习项目/OpenRLHF/README.md`、`openrlhf/utils/agent.py`、`examples/python/agent_func.py`、`examples/python/reward_func.py`、`examples/scripts/train_reinforce_baseline_ray_agent_async.sh`。官方仓库：https://github.com/OpenRLHF/OpenRLHF 。
- `F:/longchain/实习项目/BrowserGym/README.md`、`browsergym/core/README.md`、`demo_agent/agent.py`。项目论文：https://arxiv.org/abs/2412.05467 。
- MyPaperWeb 自身：`app/agents/research_workflow_service.py`、`app/context/builder.py`、`app/services/run_trace_service.py`、`app/evaluation/runner.py` 和 `app/evaluation/metrics.py`。

本设计依据本地下载版本检查，不代表在本设计日期重新核对了上游仓库的最新提交、API 或 license；实现前需记录各仓库 commit hash 并复核许可证。
