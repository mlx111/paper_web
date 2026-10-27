---
name: "workflow-checkpoint-resume"
description: "Adds checkpoint/resume (断点恢复) to LangGraph or YAML workflow services in mypaperweb, verified by hard-crash tests. Invoke when wiring crash recovery, resuming interrupted runs, or LangGraph AsyncSqliteSaver persistence."
---

# 工作流断点恢复接入与硬崩溃验证（mypaperweb）

给本项目的工作流服务（PPT/研究等模块）增加「中途失败 → 从断点续跑、跳过已完成步骤」的能力，并通过 `docker kill` 硬崩溃模拟端到端验证。

## 0. 先选型：两套引擎，两种断点机制

| 流程形态 | 引擎 | 断点机制 | 参考实现 |
|---|---|---|---|
| **固定线性步骤**（每步明确输入→输出，无循环） | YAML 工作流引擎 `app/services/workflow_engine.py` | 内置 `CheckpointManager`：每步 JSON 落盘 `data/checkpoints/.../step_NNN.json` + `latest.json`，失败从该步重跑 | PPT 管线 `app/workflows/presentation.yaml`（9 个 `call_service` 步骤） |
| **LangGraph 动态 agent 图**（含 agent⇄tools 循环、judge 反思、LLM 运行时决策） | LangGraph 原生 | LangGraph checkpointer（`AsyncSqliteSaver`），SQLite 持久化每节点状态 | 研究模块 `app/agents/research_workflow_service.py` |

**关键判断**：LangGraph agent 图**不要**重写成 YAML——循环条件是 LLM 对消息的复杂判断、工具调用是运行时即兴发起的，YAML 的 while/if 承载不了。动态图用原生 checkpointer；需要跨模块编排时，把整个研究/PPT 服务作为 YAML 的一个 `call_service` 步骤。

## 1. YAML 线性管线（CheckpointManager 已内置）

- 步骤定义在 `app/workflows/<name>.yaml`，用 `call_service` 调已注册的 Python 服务方法（`service_registry` 注册）。
- 参数用 `{{var}}` / `{{prepare_result.field}}`；`_resolve_arg` 对纯 `{{var}}` 保留 list/dict/None 原始类型（混合模板才字符串化）。
- 执行用 `CheckpointManager.run` / `run_stream`，自动：每步前存 in_progress、成功存 completed、失败存 failed 并 break；恢复时 completed→下一步，in_progress/failed→重跑该步。
- 注意 `WorkflowContext.get` 必须原样返回 None（不能把 None 替换成默认空串，否则 `target_pages=None` 变 `""` 传错类型）。

## 2. LangGraph 图接入 AsyncSqliteSaver

### 依赖
- `requirements.txt` 加 `langgraph-checkpoint-sqlite>=3.1.1`（自动带 `aiosqlite`）。
- 版本要与 `langgraph-checkpoint` 大版本匹配（checkpoint 4.x ↔ sqlite saver 3.x）。装完 `docker compose up -d --build backend`。

### 异步服务必须用 AsyncSqliteSaver（最易踩坑）
- 走 `ainvoke/astream` 的流程**必须**用 `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver`；同步 `SqliteSaver` 的 `aget_tuple/aset_tuple` 会抛 `NotImplementedError`。
- `AsyncSqliteSaver.from_conn_string(db_path)` 返回的是 **async 上下文管理器**，不是 saver 实例。在服务单例里 `__aenter__()` 后常驻持有（生命周期与服务一致，不要 `__aexit__`）。
- saver 需要在 async 上下文创建 → 图**延迟编译**：`__init__` 里只 `self.workflow = self._build_workflow()`，首次 async 调用时 `await self._ensure_app()`（加 `asyncio.Lock` 双检）再 `workflow.compile(checkpointer=saver)`。
- import 失败/初始化失败要**降级**：`compile(checkpointer=None)`，行为退回无持久化，不能让服务起不来。
- db 放持久化卷：`<artifact_root>/checkpoints/xxx.sqlite`（容器内 `/app/app/data/...`，挂 app-data 卷）。

### thread_id 与续跑决策（每个服务各自实现 sidecar）
- 每次"一次完整运行"分配唯一 thread_id：`f"{session_id}:run:{uuid4().hex[:12]}"`。
- 在 session 目录写 `run_state.json`：`{run_id, question, status}`，status ∈ running/done/failed/awaiting_selection。
- `_resolve_thread(session_id, question, confirmed)`：
  - **续跑判断优先**：若 run_state.question 与本次问题完全相同 **且** status ∈ {running, failed} → 复用该 run_id，`is_resume=True`（无论是否 confirmed）。
  - 否则新建 run_id、status=running。
- 调用：`config={"configurable": {"thread_id": thread_id}}`；
  - 续跑：`app.astream(None, config=config, ...)` / `app.ainvoke(None, config=config)`（**传 None**，LangGraph 从最后完成节点继续，已完成节点自动跳过）。
  - 新跑：传完整 inputs。
- 状态收尾：成功 `done`、clarify 暂停 `awaiting_selection`、异常 `failed`（except 里也要 mark）。
- 不参与续跑的子流程（如 clarify 阶段只取候选）用一次性 thread：`f"{session_id}:{tag}:{uuid hex}"`。

### 续跑两个必做处理（否则恢复了也跑不完/落盘残缺）
1. **重置循环预算**：崩溃时 `tool_rounds`/`num_feedback_requests` 可能已接近上限，原样还原会让续跑很快触顶、LLM 还没写报告就被强制结束。续跑开头用官方 API 清零：
   `await app.aupdate_state(config, {"tool_rounds": 0, "num_feedback_requests": 0})`（已完成节点不会重跑，只归零计数器；失败不阻断续跑）。
2. **从 checkpoint 补全状态**：流式续跑时 `streamed_messages`/`final_state_values` 只含续跑后的节点。跑完后用 `snap = await app.aget_state(config)`，把 snap.values 里 branches/learnings/sources/refined_query/research_plan 等字段回填（只在本地为空时填），保证落盘 artifact 不丢内容；最终报告若本次流式片段里没有，回退到 snap 的 messages 里 `_extract_final_answer`。

## 3. 硬崩溃验证流程（必做）

1. **正常跑通**：`POST /<module>/chat_stream`（SSE）走完 clarify→确认候选(`confirm_candidate`)→完整运行→报告 + artifacts 落盘；看 sqlite WAL 随节点增长、日志出现 `checkpointer 已启用`。
2. **崩溃前确认状态**：run_state=running、clarification_state=confirmed。
3. **硬崩**：运行到中段（agent 检索/搜索阶段，约起 50–60s）后 `docker kill <backend容器>`。
4. **重启后先发请求前**读状态文件：确认 run_state/clarification_state 跨重启仍在（验证落持久化卷）。
5. `docker compose start backend`（或 up -d），重发**同一 sessionId + 同一问题**。
6. **预期**：日志出现「检测到未完成的运行，断点续跑」「已重置循环预算」；SSE 不重放 clarify/refine/分支检索/规划，直接从崩溃处节点继续；最终产出完整报告 + final_report.md。

### 排查工具
- 查 checkpoint 线程/节点数：sqlite 表为 `checkpoints`、`writes`；`SELECT DISTINCT thread_id`、按线程 count。`next`（待执行节点）在 checkpoint BLOB 内，不在独立列。
- 用服务自身 saver 读快照最准：脚本里 `await svc._ensure_app()` 后 `app.aget_state(config)`，看 `snap.next`（空元组=已到 END）、`snap.values` 的计数器和最后一条 message。
- **边界**：若崩溃线程 `snap.next == ()` 说明崩溃前图已耗尽循环到终态，续跑无节点可跑——这正是"续跑重置循环预算"要解决的场景；中段崩溃（next 非空）续跑会继续执行。

## 4. 项目环境事实（避免重复踩坑）

- 容器 `mypaperweb-backend-1`；代码 `/app/app`（包根，import 如 `from agents.xxx import ...`），数据 `/app/app/data`（app-data 卷，checkpoint/artifact 都在这）。
- 改代码必须重建：`docker compose up -d --build backend`（代码非挂载）；仅重启 `docker compose start backend`。
- 容器内跑调试脚本：写到本地文件 → `docker cp x.py <容器>:/tmp/x.py` → `docker exec -e PYTHONPATH=/app/app -w /app/app <容器> python /tmp/x.py`。**不要**用 PowerShell 内联 `python -c "..."`（引号/逗号会被 PowerShell 拆坏）。
- PowerShell 旧版不支持 `&&`，用 `;` 串联。
- `tools.websearch_tool.web_search` 是 langchain `@tool` 装饰的 StructuredTool，不能直接调用，用 `web_search.invoke({"query": q})`（try/except 兜底）。
- SSE 测试：`Invoke-WebRequest ... -OutFile out.txt`，输出文件被占用时别用 Get-Content 读（改看 `docker logs`）。
- 提交：只 `git add` 精确源码路径（勿 `git add -A`，`.trae/`、临时脚本、测试 txt 不入库）；commit message 用单行 `-m`。
