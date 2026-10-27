# ShopPilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `mypaperweb copy` 内交付独立、可复现的多轮电商 Agent 任务环境、搜索计划、轨迹奖励、评测与报告，为有 GPU 时的 SFT/GRPO 留好适配接口。

**Architecture:** ShopPilot 放在 `app/agent_algo/shopilot`，不改现有 Agent、router、evaluation schema、trace service 或数据库。确定性 ShopEnv 负责任务状态和硬奖励，policy adapter 调用模型并输出结构化 action，ShopPilot runner 保存轨迹并产出指标；MyPaperWeb 的 Context/Memory/Trace 只在后续通过 adapter 复用。

**Tech Stack:** Python 3.11+、Pydantic（仓库现有版本）、pytest、JSONL、现有 MyPaperWeb Trace/LLM factory 的可选 adapter。首期不新增运行时依赖，不要求 GPU、Ray、vLLM、DeepSpeed 或 BrowserGym。

**Design:** `docs/superpowers/specs/2026-10-27-shoppilot-design.md`

---

## 工作区与执行规则

- Repository root: `F:/longchain/实习项目/mypaperweb copy`。
- `F:/longchain/实习项目/mypaperweb`、`OpenRLHF`、`tau-bench`、`BrowserGym` 为只读参考。
- 副本已有未提交修改。开始实施前和每项任务完成后运行 `git status --short`；只 stage 新增的 ShopPilot 文件。禁止 `git add -A`、全局格式化、恢复已有改动或改动共享模块。
- 上游参考只学习接口/实验模式。先记录本机参考仓库 commit hash 和 LICENSE；旧 `tau-bench` Retail 数据标为过时，不直接拿它做最终 benchmark。
- 每一项以离线测试优先；涉及模型 API 的测试使用 stub。需要真实 API/GPU 的实验单独标成 optional，不作为核心单测门槛。

## 文件职责

| 路径 | 责任 |
| --- | --- |
| `app/agent_algo/shopilot/types.py` | Task、Action、Observation、StepResult、RewardBreakdown、EpisodeResult 数据协议 |
| `app/agent_algo/shopilot/task_loader.py` | JSONL schema 校验、split 加载、重复模板/实体检查 |
| `app/agent_algo/shopilot/env.py` | 隔离 episode 状态、reset/step、步数限制与终局状态 |
| `app/agent_algo/shopilot/tools.py` | 零售工具 schema、只读/写操作标签、参数和状态转换验证 |
| `app/agent_algo/shopilot/plan_schema.py` | SearchPlan Pydantic 类型和 schema version |
| `app/agent_algo/shopilot/planner.py` | 对话目标/约束抽取及每轮计划更新 adapter |
| `app/agent_algo/shopilot/memory_adapter.py` | deterministic memory-on/off 条件、来源追踪和槽位匹配 |
| `app/agent_algo/shopilot/policy.py` | 统一 policy protocol、D0 离线启发式、模型 ReAct optional、计划策略与候选动作生成 |
| `app/agent_algo/shopilot/action_reranker.py` | 纯 Python 线性 pairwise ranking 训练、动作打分与确定性 tie-break |
| `app/agent_algo/shopilot/preference_data.py` | train split 同状态候选动作克隆 rollout、pairwise preference 提取 |
| `app/agent_algo/shopilot/reward.py` | Gold state 验收、约束满足和可审计 reward breakdown |
| `app/agent_algo/shopilot/trajectory.py` | Step/Episode trajectory 结构、JSONL 序列化与版本号 |
| `app/agent_algo/shopilot/metrics.py` | 完成率、约束、工具、效率、安全指标 |
| `app/agent_algo/shopilot/runner.py` | 固定 seed 执行、baseline 对照和聚合 |
| `app/agent_algo/shopilot/report.py` | JSON/Markdown 报告、分桶结果、失败案例 |
| `app/agent_algo/shopilot/data/*.jsonl` | 12 个任务族的 60 train、12 dev、18 test；Gold 字段不能出现在 Observation |
| `scripts/generate_shopilot_tasks.py` | 可复现的合成任务模板生成、字段校验和 split 导出 |
| `scripts/run_shopilot_eval.py` | CLI 入口、模型选择、baseline/实验配置和报告路径 |
| `scripts/export_shopilot_trajectories.py` | 脱敏轨迹导出为训练用 JSONL |
| `tests/test_shopilot_*.py` | 独立环境、协议、奖励、任务数据、runner、policy、reranker 测试 |
| `docs/shopilot/README.md` | 本地运行、任务 schema、指标定义、实验复现说明 |
| `docs/shopilot/experiment-report.md` | 实测基线、消融、失败分析和限制；只填真实结果 |

## Task 1: 建立 ShopPilot 包与数据契约

**Files:**
- Create: `app/agent_algo/__init__.py`
- Create: `app/agent_algo/shopilot/__init__.py`
- Create: `app/agent_algo/shopilot/types.py`
- Create: `app/agent_algo/shopilot/task_loader.py`
- Create: `tests/test_shopilot_data.py`

- [ ] **Step 1: 为 task schema 和 loader 写失败测试**

覆盖合法 task 读入、未知字段/缺字段拒绝、重复 task id、非法 split、gold 字段与用户可见 observation 字段隔离。

- [ ] **Step 2: 验证失败**

Run: `pytest tests/test_shopilot_data.py -q`
Expected: 因包/类型/loader 尚不存在而失败。

- [ ] **Step 3: 实现最小数据协议**

定义带版本的 Task/Action/Observation/StepResult/RewardBreakdown/EpisodeResult；loader 逐行解析 JSONL，报错信息包括文件、行号和字段，不静默跳过错误记录。所有 ID 唯一，`split` 只允许 `train|dev|test`。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/test_shopilot_data.py -q`
Expected: PASS。

- [ ] **Step 5: 检查工作区差异**

Run: `git status --short`
Expected: 只看到上述 ShopPilot 新文件增加；不 stage 或改动其他既存变化。

## Task 2: 实现确定性零售工具与 episode 环境

**Files:**
- Create: `app/agent_algo/shopilot/tools.py`
- Create: `app/agent_algo/shopilot/env.py`
- Create: `tests/test_shopilot_env.py`

- [ ] **Step 1: 写环境状态机失败测试**

覆盖 reset 隔离、商品查询、比较、订单查询、取消/退款确认、未授权写操作拒绝、错误工具/参数、重复调用计数和 `max_steps` 停止。

- [ ] **Step 2: 验证失败**

Run: `pytest tests/test_shopilot_env.py -q`
Expected: 缺少 Env/tools 实现时失败。

- [ ] **Step 3: 实现工具目录和 ShopEnv**

工具协议为一个 action 对应一个 tool call；每个工具有 JSON 参数 schema、read/write 分类、前置状态与确定性输出。`reset(task_id, seed)` 深拷贝 episode 初始状态；`step(action)` 返回稳定错误码和状态 diff。写操作需在 env 状态机中验证本轮明确授权，不允许由模型自行声明已授权。

- [ ] **Step 4: 验证环境测试通过**

Run: `pytest tests/test_shopilot_env.py -q`
Expected: PASS，且不同 task 的状态对象互不共享。

- [ ] **Step 5: 跑相关协议测试**

Run: `pytest tests/test_shopilot_data.py tests/test_shopilot_env.py -q`
Expected: PASS。

## Task 3: 制作可验证任务集与生成器

**Files:**
- Create: `app/agent_algo/shopilot/data/catalog.json`
- Create: `app/agent_algo/shopilot/data/orders.json`
- Create: `app/agent_algo/shopilot/data/tasks_train.jsonl`
- Create: `app/agent_algo/shopilot/data/tasks_dev.jsonl`
- Create: `app/agent_algo/shopilot/data/tasks_test.jsonl`
- Create: `scripts/generate_shopilot_tasks.py`
- Modify: `tests/test_shopilot_data.py`

- [ ] **Step 1: 定义任务覆盖矩阵和 split 测试**

为多约束商品搜索/比较、缺槽澄清、偏好记忆、物流/订单查询、需确认售后、工具失败恢复、无结果和冲突约束建立分类断言；允许 task family 跨 split，但 `template_variant`、实体 ID、约束组合和语言改写实例必须按 spec 隔离，不能共享实例或派生副本。

- [ ] **Step 2: 生成器先以测试证明可复现性**

测试固定 seed 重复生成结果一致、任务数符合配置、gold state/action 可由 env 执行、每个 split 覆盖预期 task family、无 template variant/实体/约束实例泄漏、Observation 中不含 gold 字段。

- [ ] **Step 3: 实现合成生成器与首版任务数据**

目标 60/12/18 条 train/dev/test；12 个任务族各有 5 train、1 dev、1 普通 test，另有 6 条跨族 stress test。生成器为实体填充和语言模板保存 version/seed。LLM 仅能用于额外 paraphrase，不作为结构字段或目标状态的来源。

- [ ] **Step 4: 验证任务可达性与泄漏检查**

Run: `python scripts/generate_shopilot_tasks.py --seed 20261027 --check`
Expected: 输出各 split 数量、任务类别覆盖、duplicate 检查和 schema check；非法 task 返回非零退出码。

Run: `pytest tests/test_shopilot_data.py -q`
Expected: PASS。

## Task 4: 加入 SearchPlan 和 planner adapter

**Files:**
- Create: `app/agent_algo/shopilot/plan_schema.py`
- Create: `app/agent_algo/shopilot/planner.py`
- Create: `app/agent_algo/shopilot/memory_adapter.py`
- Create: `tests/test_shopilot_policy.py`

- [ ] **Step 1: 写 plan schema/update 测试**

验证硬约束/软偏好区分、缺失槽位识别、子目标完成状态、停止条件、schema version 和畸形模型输出的拒绝/修复路径。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_shopilot_policy.py -q`
Expected: 计划类型和 planner adapter 缺失时失败。

- [ ] **Step 3: 实现严格结构化计划**

用 Pydantic schema 校验，不把隐式 CoT 暴露为必须输出。planner 只输出可验收字段；支持注入确定性 stub，模型不可用或解析失败时返回显式 `plan_parse_error`，不默认为全部完成。

- [ ] **Step 4: 验证 schema 测试通过**

Run: `pytest tests/test_shopilot_policy.py -q`
Expected: PASS。

- [ ] **Step 5: 写 memory-on/off 测试**

同一 task/seed 下分别运行 memory-off 和 memory-on；断言只注入带来源的历史偏好，最多 3 条，gold constraint 不会伪装成 memory，错误槽位/重复记录不被注入，并记录 expected hit、wrong injection 和 duplicate injection。

- [ ] **Step 6: 实现 deterministic memory adapter**

读取 task 的 `memory_items`，按 `type` 和规范化槽位匹配选择记录；memory-off 返回空上下文；每次选择输出 `memory_id/source_turn_id`，不调用 LLM、不读 test labels。

- [ ] **Step 7: 验证 memory 条件通过**

Run: `pytest tests/test_shopilot_policy.py -q`
Expected: PASS，且 memory-on/off 的其他输入、seed 和工具预算一致。

## Task 5: 实现 baseline 与 planned policy 接口

**Files:**
- Create: `app/agent_algo/shopilot/policy.py`
- Modify: `tests/test_shopilot_policy.py`

- [ ] **Step 1: 写 policy protocol 测试**

同一 stub model、env、task 下验证 baseline 和 planned policy 都返回合法 Action；planned policy 按计划顺序调用工具；工具不在 allowlist、格式错误和超步数均被 harness 拦截。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_shopilot_policy.py -q`
Expected: policy 接口缺失。

- [ ] **Step 3: 实现可插拔 policy**

定义 `reset(observation)` / `act(observation, history, plan)` / `observe(step_result)`。D0 是无网络的确定性启发式 policy；B1 使用 SearchPlan；B1G 另加 policy-level guard；B2 在 planned policy 上使用 reward-aware reranker。模型调用通过依赖注入，不在环境/奖励模块直接创建 LLM。所有 policy 通过 ShopEnv observation 接收当前用户回合，确认状态由 ShopEnv 推进。明确 single action per step，并复用仓库现有模型工厂时走独立 factory adapter，不能改全局 LLM 配置。

- [ ] **Step 4: 验证 policy 测试通过**

Run: `pytest tests/test_shopilot_policy.py -q`
Expected: PASS。

## Task 6: 实现可审计奖励和风险硬门槛

**Files:**
- Create: `app/agent_algo/shopilot/reward.py`
- Create: `tests/test_shopilot_reward.py`

- [ ] **Step 1: 写终局状态和 reward hacking 测试**

包含成功、漏硬约束、错误商品、回答声称未发生的操作、重复读工具、过早停止、未授权写操作和失败 episode 不能靠效率分数翻盘。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_shopilot_reward.py -q`
Expected: reward evaluator 缺失。

- [ ] **Step 3: 实现 reward breakdown**

Gold predicate 仅对 evaluator 可见；硬约束和安全 violation 用 gate/硬失败表达；软分项以配置记录版本和权重。计算 `progress` 需来自 subgoal 状态差分；效率 reward 仅在 success episode 生效；reward 不调用外网或 LLM judge。

- [ ] **Step 4: 验证 reward 测试通过**

Run: `pytest tests/test_shopilot_reward.py -q`
Expected: PASS，非法 reward 权重或 NaN 应被拒绝。

## Task 7: 实现 reward-aware action reranker

**Files:**
- Create: `app/agent_algo/shopilot/action_reranker.py`
- Create: `app/agent_algo/shopilot/preference_data.py`
- Create: `app/agent_algo/shopilot/configs/reranker.json`
- Create: `scripts/train_shopilot_reranker.py`
- Create: `tests/test_shopilot_reranker.py`

- [ ] **Step 1: 写动作特征与 pairwise 学习测试**

用固定合成样本测试特征维度/归一化、同 state 候选分支 rollout、终局 reward 高低决定 pair 标签、无 reward 差异时丢弃 pair、梯度更新方向、固定初始化/seed 可复现以及 tie-break 次序。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_shopilot_reranker.py -q`
Expected: reranker 模块缺失时失败。

- [ ] **Step 3: 实现线性 pairwise ranking**

候选动作最多 3 个。`preference_data.py` 在同一 train episode state 深拷贝环境，对每个 candidate 执行动作，再用固定 continuation policy rollout 到终局；仅将终局 reward 不同的候选组成 preferred/rejected pair。使用明确定义的 state/plan/action 特征训练线性 pairwise 权重。实现固定 rollout seed、候选生成器版本、学习率、epoch、正则和空 pair 行为。训练脚本只读取 train split，只保存 weights/config JSON，不需要 torch/GPU，不读取 dev/test reward。

- [ ] **Step 4: 验证学习与复现测试**

Run: `pytest tests/test_shopilot_reranker.py -q`
Expected: PASS。

Run: `python scripts/train_shopilot_reranker.py --split train --seed 20261027 --output app/agent_algo/shopilot/data/reranker.json`
Expected: 输出 train task/pair 数量、reward 差异分布、配置 hash 和模型文件；若无有效 pair 则返回明确错误，不保存伪造权重。

- [ ] **Step 5: 连接 B2 planned policy**

在 `policy.py` 中让 B2 对同一 state 下候选动作打分并选择最高分；候选数、特征版本和 reranker 权重版本写入每条 trajectory metadata。B1/B1G 不加载 reranker。

## Task 8: 轨迹、指标和基准 runner

**Files:**
- Create: `app/agent_algo/shopilot/trajectory.py`
- Create: `app/agent_algo/shopilot/metrics.py`
- Create: `app/agent_algo/shopilot/runner.py`
- Create: `tests/test_shopilot_runner.py`

- [ ] **Step 1: 写轨迹兼容与 runner 测试**

覆盖 JSONL round trip、schema version、每步工具调用关联 observation、相同 seed 重放、模型异常分类、空数据集、split 固定和 report 所需字段。

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_shopilot_runner.py -q`
Expected: runner/trajectory/metrics 未定义时失败。

- [ ] **Step 3: 实现 episode runner 与指标**

每次运行固定 task order 和 seeds；逐步保存 plan/action/result/reward/error/latency；trajectory 里的 raw user/model text 先经 Trace service 相同敏感键脱敏思想处理。核心指标按任务数作分母，重复工具和必要工具分别统计，safe-write violations 单独报告。

- [ ] **Step 4: 验证 runner 测试通过**

Run: `pytest tests/test_shopilot_runner.py -q`
Expected: PASS，且失败 episode 仍被记录，不丢弃。

## Task 9: 报告、CLI 和失败分类

**Files:**
- Create: `app/agent_algo/shopilot/report.py`
- Create: `scripts/run_shopilot_eval.py`
- Modify: `tests/test_shopilot_runner.py`

- [ ] **Step 1: 写 CLI/report 测试**

使用 fake policy 对 train/dev/test 跑评测，断言 JSON/Markdown 包含配置、样本数、分桶指标、置信区间、失败样例、hard safety violations 和可复现实验 seed。

- [ ] **Step 2: 实现 CLI 和聚合报告**

CLI 参数包括 `--split`、`--agent`、`--seed`、`--config`、`--output-dir`；默认不运行真 API，缺少 provider 配置时明确报错。test 权重/阈值读取已冻结 config。

- [ ] **Step 3: 验证离线端到端流程**

Run: `python scripts/run_shopilot_eval.py --split dev --agent stub --seed 20261027 --output-dir app/data/shopilot/reports/smoke`
Expected: exit 0，生成 report JSON/Markdown 和 episode trajectories。

Run: `pytest tests/test_shopilot_runner.py -q`
Expected: PASS。

## Task 10: 数据导出和 OpenRLHF 训练 adapter 设计

**Files:**
- Create: `scripts/export_shopilot_trajectories.py`
- Create: `tests/test_shopilot_export.py`
- Create: `docs/shopilot/training-adapter.md`

- [ ] **Step 1: 先定义训练导出 schema 测试**

确保每个 action/reward/done 对齐，含 task id、split、seed、policy version、reward breakdown；API key、路径、未脱敏身份和 test gold labels 不允许进入训练文件。

- [ ] **Step 2: 实现 JSONL exporter**

导出适合进一步转换为 SFT/DPO/RL 的 canonical JSONL；默认仅允许 train split，dev/test 需要显式 `--allow-eval-split` 并在文件 metadata 写明，避免误训污染。

- [ ] **Step 3: 写训练阶段适配说明，不引入训练依赖**

说明本地 OpenRLHF `AgentExecutorBase` 需要怎样映射 ShopEnv reset/step，reward function 输入如何获取 task metadata，候选多轮轨迹怎样聚合；注明依赖版本/commit、GPU 前提和未验证事项。首期不要安装 OpenRLHF 栈或新增主项目依赖。

- [ ] **Step 4: 验证导出和敏感字段清理**

Run: `pytest tests/test_shopilot_export.py -q`
Expected: PASS。

## Task 11: 实验对照与消融

**Files:**
- Create: `docs/shopilot/experiment-protocol.md`
- Create: `docs/shopilot/experiment-report.md`
- Create: `app/agent_algo/shopilot/configs/baseline.json`
- Create: `app/agent_algo/shopilot/configs/ablation_*.json`

- [ ] **Step 1: 固定实验协议**

预先声明 D0 offline heuristic、B1 SearchPlan-only、B1G SearchPlan+guard、B2 SearchPlan+fixed pairwise action reranker 的 memory-off 条件，以及 B2+memory-on 条件和可选 B0 raw ReAct 的模型、prompt、temperature、环境版本、task split、seed、阈值和成本限制；所有学习配置选择仅用 dev。

- [ ] **Step 2: 运行开发集 smoke 和基线**

先对 5 条 dev task 检查完整轨迹，再固定配置跑全部 dev；离线必跑 D0/B1/B1G/B2-off/B2-on，B0 只有模型配置存在时运行。若调用模型 API，B0 用 5 个预先固定 seeds（`11, 23, 37, 53, 71`），报告每项均值、标准差及真实模型 id、版本、运行时间和 token/cost；调用成本不足以完成五次时标记为探索性结果。失败调用单独标记。

- [ ] **Step 3: 冻结主方法配置后跑测试集**

只在最终配置冻结后运行 test；按同 task/seed 配对比较 D0、B1、B1G、B2-off、B2-on，B0 使用相同的 5 个固定 seeds 并单独标记 optional。报告区间、任务类别、memory hit/wrong injection 分桶；确定性策略报告单次可复现结果，B0 报告均值和标准差。

- [ ] **Step 4: 做 reward 消融**

分别移除 progress、效率/重复项、软约束/grounding 项；不移除安全 gate。清楚注明如果某一组件尚未实现，则不声称有该消融结果。

- [ ] **Step 5: 完成 memory ablation**

固定 B2 reranker 和环境，仅切换 memory-off/on；报告 memory-assisted constraint satisfaction、expected memory hit、wrong injection、duplicate injection 和失败类别变化。若 memory-on 没有提升或产生误注入，保留负结果并说明原因。

- [ ] **Step 6: 完成失败分析和限制**

挑选成功/失败轨迹做逐步解释，讨论模板偏差、模拟与真实流量差距、模型随机性、reward 权重敏感性及是否有 GPU 训练。不得预填目标或虚构结果。

## Task 12: 文档、范围检查和回归

**Files:**
- Create: `docs/shopilot/README.md`
- Review: all files under `app/agent_algo/shopilot/`, `scripts/*shopilot*`, `tests/test_shopilot_*`, `docs/shopilot/`

- [ ] **Step 1: 写运行与复现文档**

列出 Python 环境、离线 smoke、真实模型配置方法、数据字段、reward 公式/权重版本、指标口径、报告位置和训练 adapter 状态。

- [ ] **Step 2: 运行 ShopPilot 全部离线测试**

Run: `pytest tests/test_shopilot_*.py -q`
Expected: 所有 ShopPilot 测试通过。

- [ ] **Step 3: 运行相关现有回归测试**

Run: `pytest tests/test_research_workflow_service_v2.py tests/test_evaluation_runner_trace_integration.py tests/test_run_trace_service.py -q`
Expected: PASS；若失败，先判断是否由新增路径导入/副本的既存改动导致，不能修改无关源码掩盖问题。

- [ ] **Step 4: 检查范围与工作树**

Run: `git status --short`
Run: `git diff --check`
Run: `git diff --stat -- app/agent_algo/shopilot scripts tests docs/shopilot docs/superpowers`
Expected: ShopPilot 改动限定在新增路径；副本的既存 dirty files 仍保留；原始 `mypaperweb` 没有变更。

## 可选 Task 13: 有 GPU 时的 SFT/GRPO 阶段

此项不属于首期验收，必须先确认可用 GPU 显存、驱动/CUDA、模型许可、训练时长和 OpenRLHF 当前 checkout 的 commit。

**Files:**
- Create: `app/agent_algo/shopilot/openrlhf_adapter.py`
- Create: `app/agent_algo/shopilot/training/reward_func.py`
- Create: `app/agent_algo/shopilot/training/agent_executor.py`
- Create: `app/agent_algo/shopilot/training/train_grpo.sh`
- Create: `tests/test_shopilot_openrlhf_adapter.py`

- [ ] 用 fake rollout/CPU contract tests 验证每个动作与 observation token span 和 reward episode 对齐。
- [ ] 先做少量 SFT smoke，保存 base/model/data/config/seed hash。
- [ ] 再用同一数据与 evaluator 比较 SFT、GRPO/REINFORCE；监控 reward 方差、成功率、KL、输出长度、非法工具率和崩溃率。
- [ ] 小步验证通过后扩大 rollout；不得只展示训练 reward 上升，要在冻结 test task 上验证行为指标。

## 验收清单

- [ ] 所有 ShopPilot 代码和新增数据均在 `mypaperweb copy`。
- [ ] 环境完全离线运行，task state 在 episode 间隔离，写工具需要授权。
- [ ] gold state/labels 不进入 Agent prompt 或 tool output。
- [ ] D0、B1、B1G、B2-off、B2-on 在相同 task/seed 上比较，B0 仅在模型配置存在时作为 optional 对照，终局成功由环境 oracle 判定。
- [ ] 报告包含 hard safety gate、失败分桶、步骤/成本指标和真实限制。
- [ ] JSONL export 可复现、已脱敏，eval split 默认不进入训练。
- [ ] OpenRLHF/τ-bench/BrowserGym 仅按 license 和版本规则参考，没有复制未授权代码或旧 benchmark 结果。
- [ ] 既有副本的未提交修改全部保留；原 `mypaperweb` 不变。
