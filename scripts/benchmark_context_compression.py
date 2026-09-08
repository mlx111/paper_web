"""
Benchmark script for Hermes-style Context Compression.

Generates realistic multi-turn conversations (with tool calls, system prompts,
constraints) and runs them through ContextCompressorService to measure:

  - Pre/post token counts
  - Token savings ratio
  - Content preservation (constraints, citations, recent dialogue)
  - Thrash warning trigger count
  - Multiple compression cycles
"""

import sys
from pathlib import Path

_app_dir = str(Path(__file__).parent.parent / "app")
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

# Ensure the project root is also on sys.path for any cross-references
_root_dir = str(Path(__file__).parent.parent)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger

from app.services.context_compressor_service import (
    CompressorConfig,
    ContextCompressorService,
    _total_tokens,
)


# ---------------------------------------------------------------------------
# realistic conversation builders
# ---------------------------------------------------------------------------

def _make_tool_call(
    name: str,
    args: dict,
    tool_call_id: str,
    content: str = "",
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[{"name": name, "args": args, "id": tool_call_id}],
    )


def _make_tool_result(
    content: str,
    name: str,
    tool_call_id: str,
) -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=tool_call_id)


def build_short_conversation() -> list[BaseMessage]:
    """~5 turns, well under 16K trigger — should NOT compress."""
    return [
        SystemMessage(content="你是 MyPaperWeb 科研助手。请用中文回答。"),
        HumanMessage(content="搜索最近关于 LLM 评估的论文"),
        _make_tool_call("web_search", {"query": "LLM evaluation papers 2025"}, "call_1"),
        _make_tool_result("找到 3 篇论文: 1. RAGAS 2.  BFCL 3. AgentEval", "web_search", "call_1"),
        AIMessage(content="我搜索到以下三篇重要论文：RAGAS（评估 RAG 系统）、BFCL（函数调用评测）和 AgentEval。"),
        HumanMessage(content="帮我搜一下上下文工程的最新进展"),
        _make_tool_call("web_search", {"query": "context engineering LLM 2025"}, "call_2"),
        _make_tool_result(
            "Context Engineering 2025 趋势：1. 结构化上下文构建 2. 动态压缩 3. Hermes Agent 风格压缩",
            "web_search",
            "call_2",
        ),
        AIMessage(content="上下文工程的最新进展主要包括：结构化上下文构建、动态压缩策略、以及 Hermes Agent 风格的四阶段压缩方法。"),
    ]


def build_long_conversation() -> list[BaseMessage]:
    """~20 turns with multiple tool calls — well over 16K trigger."""
    msgs: list[BaseMessage] = [
        SystemMessage(
            content="你是 MyPaperWeb 科研助手。\n"
            "约束条件：\n"
            "1. 始终用中文回答\n"
            "2. 每次回答必须提供引用来源\n"
            "3. 不要编造数据\n"
            "4. 优先使用检索到的信息而非自身知识"
        ),
    ]

    # Round 1: search papers
    msgs.append(HumanMessage(content="帮我搜索关于 Agent 评估的论文"))
    msgs.append(_make_tool_call("web_search", {"query": "agent evaluation benchmark 2025"}, "r1c1"))
    msgs.append(_make_tool_result(
        "Results: 1. AgentBench 2. SWE-bench 3. GAIA 4. AgentEval\n"
        "AgentBench covers 7 environments including OS, web, database.\n"
        "SWE-bench focuses on software engineering tasks.\n"
        "GAIA tests general AI assistants on real-world tasks.\n"
        "AgentEval from Microsoft measures agent capabilities.", "web_search", "r1c1",
    ))
    msgs.append(AIMessage(content="搜到以下 Agent 评估基准：AgentBench（7 环境）、SWE-bench（软件工程）、GAIA（通用任务）、AgentEval（微软）。其中 AgentBench 覆盖最广。"))

    # Round 2: search context compression
    msgs.append(HumanMessage(content="搜索上下文压缩的最新方法"))
    msgs.append(_make_tool_call("web_search", {"query": "LLM context compression techniques 2025"}, "r2c1"))
    msgs.append(_make_tool_result(
        "Techniques:\n"
        "- Selective Context: 选择性地保留重要内容\n"
        "- LLMLingua: 用小型模型压缩提示\n"
        "- Hermes Agent: 四阶段压缩（修剪+边界+摘要+清洗）\n"
        "- AutoCompressors: 使用压缩 token\n"
        "- ICAE: 使用自编码器压缩\n"
        "Hermes Agent achieves 4x compression with minimal quality loss.",
        "web_search", "r2c1",
    ))
    msgs.append(AIMessage(content="上下文压缩技术包括：Selective Context（选择性保留）、LLMLingua（小模型压缩）、Hermes Agent（四阶段）、AutoCompressors（压缩 token）、ICAE（自编码器）。Hermes Agent 可达到 4 倍压缩。"))

    # Round 3: deep comparison
    msgs.append(HumanMessage(content="对比一下 Hermes Agent 和 LLMLingua 的优劣"))
    msgs.append(_make_tool_call("web_search", {"query": "Hermes Agent vs LLMLingua comparison"}, "r3c1"))
    msgs.append(_make_tool_result(
        "Comparison:\n"
        "Hermes Agent: 4-stage pipeline, preserves tool call integrity, "
        "anti-thrash mechanism, structured summary. Best for agentic workflows.\n"
        "LLMLingua: Task-agnostic, uses small LM to prune tokens. "
        "Faster but can break structured outputs. Better for simple QA.",
        "web_search", "r3c1",
    ))
    msgs.append(
        AIMessage(
            content="Hermes Agent 适合智能体工作流（保留工具调用完整性、防抖动），"
            "LLMLingua 速度快但可能破坏结构化输出（适合简单问答）。"
        )
    )

    # Round 4: add some long tool results to push token count
    msgs.append(HumanMessage(content="搜索 LangChain 集成方案"))
    msgs.append(_make_tool_call("web_search", {"query": "LangChain Hermes context compression integration"}, "r4c1"))
    long_result = "\n\n".join([
        "LangChain integration guide:\n"
        "1. Install: pip install langchain langchain-community\n"
        "2. Import: from langchain.memory import ConversationSummaryMemory\n"
        "3. Configure: memory = ConversationSummaryMemory(llm=llm, max_token_limit=2000)\n"
        "4. Use: memory.load_memory_variables({})",
        "Hermes Agent-style compression can be implemented using:\n"
        "- Custom callback handlers\n"
        "- Message filtering middleware\n"
        "- Custom memory classes",
        "Example implementation:\n"
        "class HermesCompressionMemory(BaseMemory):\n"
        "    def __init__(self, compressor):\n"
        "        self.compressor = compressor\n"
        "        self.messages = []\n"
        "    def load_memory_variables(self, inputs):\n"
        "        result = self.compressor.compress_messages(self.messages)\n"
        "        return {'history': result.messages}\n"
        "    def save_context(self, inputs, outputs):\n"
        "        self.messages.append(HumanMessage(content=inputs['input']))\n"
        "        self.messages.append(AIMessage(content=outputs['output']))",
        "This approach provides:\n"
        "- Automatic compression when context exceeds threshold\n"
        "- Preservation of recent messages\n"
        "- Structured summaries of older content",
        "For production use, consider:\n"
        "- Async processing for large contexts\n"
        "- Caching summaries to avoid redundant LLM calls\n"
        "- Monitoring compression ratios\n"
        "- Fallback strategies when LLM summarization fails",
        "Advanced Configuration:\n"
        "- Set custom context window limits per session\n"
        "- Configure compression trigger thresholds dynamically\n"
        "- Implement priority-based message retention\n"
        "- Add logging for compression effectiveness tracking",
    ])
    msgs.append(_make_tool_result(long_result, "web_search", "r4c1"))
    msgs.append(AIMessage(content="LangChain 集成可以通过自定义 Memory 类实现。核心是包装 ContextCompressorService，在每次保存上下文时触发压缩检查。需要关注异步处理、缓存和降级策略。"))

    # Round 4b: more detailed follow-up to add volume
    msgs.append(HumanMessage(content="请详细解释 Hermes 四阶段压缩的具体实现"))
    msgs.append(_make_tool_call("web_search", {"query": "Hermes Agent 4 stage compression implementation details"}, "r4b1"))
    hermes_detail = "\n\n".join([
        "Phase 1 - ToolOutputPruner:\n"
        "Purpose: Reduce verbosity of old tool results without LLM calls.\n"
        "Method: Replace multi-line tool outputs with single-line summaries.\n"
        "Format: [tool_name] status | size_bytes | preview_text\n"
        "Preserves: Most recent tool round remains verbatim.\n"
        "Deduplication: Identical tool results are collapsed to one entry.",
        "Phase 2 - BoundaryFinder:\n"
        "Purpose: Determine which parts of context to compress and protect.\n"
        "Head protection: First N messages preserved (default: 3).\n"
        "Tail budget: Last M tokens reserved for recent conversation.\n"
        "Alignment: Tool call/result pairs are never split across boundaries.",
        "Phase 3 - SummaryGenerator:\n"
        "Purpose: LLM-based structured summarization of middle zone.\n"
        "Template includes: Active Task, Goals, Completed Actions, Key Decisions.\n"
        "Handoff prefix: '[CONTEXT COMPACTION -- REFERENCE ONLY]' marks compressed content.\n"
        "Iterative: New summaries build upon existing ones rather than rewriting.",
        "Phase 4 - MessageSanitizer:\n"
        "Purpose: Fix orphan tool_call/result pairs after compression.\n"
        "Removes: ToolMessages without matching AIMessage tool_calls.\n"
        "Cleans: AIMessage tool_calls whose results are missing.\n"
        "Assembles: head + summary + sanitized-tail in correct order.",
        "AntiThrashTracker:\n"
        "Purpose: Prevent repeated ineffective compressions.\n"
        "Method: Track consecutive low-savings compression attempts.\n"
        "Threshold: Default 2 consecutive attempts below 10% savings.\n"
        "Recovery: Reset counter on successful high-savings compression.",
    ])
    msgs.append(_make_tool_result(hermes_detail, "web_search", "r4b1"))
    msgs.append(AIMessage(content="Hermes 四阶段压缩包括：ToolOutputPruner（修剪旧工具结果）、BoundaryFinder（确定保护边界）、SummaryGenerator（LLM 结构化摘要）、MessageSanitizer（清洗孤立消息对）。外加 AntiThrashTracker 防止无效重复压缩。"))

    # Round 5: more content
    msgs.append(HumanMessage(content="Milvus 的混合检索方案应该怎么配置？"))
    msgs.append(_make_tool_call("web_search", {"query": "Milvus hybrid retrieval dense sparse configuration"}, "r5c1"))
    milvus_detail = "\n".join([
        "Milvus hybrid retrieval:\n"
        "- Dense: using embedding model (e.g., bge-large-zh)\n"
        "- Sparse: using BM25 or SPLADE\n"
        "- Hybrid: weighted combination (default 0.5/0.5)",
        "Configuration:\n"
        "collection = Collection('hybrid_collection')\n"
        "collection.create_index('dense', IndexType.IVF_FLAT)\n"
        "collection.create_index('sparse', IndexType.SPARSE_INVERTED_INDEX)",
        "Search with:\n"
        "hybrid_search = HybridSearch(dense_field, sparse_field)\n"
        "hybrid_search.rerank('RRF', top_k=10)",
        "Parameter tuning:\n"
        "- nprobe: number of clusters to search (default 8)\n"
        "- top_k: number of results to return (default 10)\n"
        "- metric_type: IP or L2 for dense, IP for sparse\n"
        "- reranker: RRF or WeightedSum",
        "Performance considerations:\n"
        "- Index building time vs query speed trade-off\n"
        "- Memory usage for holding both index types\n"
        "- Optimal batch size for large-scale retrieval\n"
        "- Caching strategies for frequent queries",
    ])
    msgs.append(_make_tool_result(milvus_detail, "web_search", "r5c1"))
    msgs.append(AIMessage(content="Milvus 混合检索需同时配置稠密向量索引（如 IVF_FLAT）和稀疏向量索引（如 SPARSE_INVERTED_INDEX），搜索时使用 HybridSearch + RRF 重排序。参数调优需关注 nprobe、top_k 和重排序策略的选择。"))

    # Round 6: more tool calls with long results
    msgs.append(HumanMessage(content="RAG 评估指标有哪些？请详细说明"))
    msgs.append(_make_tool_call("web_search", {"query": "RAG evaluation metrics faithfulness relevance"}, "r6c1"))
    rag_detail = "\n".join([
        "RAG Evaluation Metrics:\n"
        "1. Faithfulness (忠实度): 答案是否基于检索到的上下文\n"
        "2. Answer Relevance (答案相关性): 答案是否回答了问题\n"
        "3. Context Precision (上下文精度): 检索结果中相关文档的比例\n"
        "4. Context Recall (上下文召回): 相关文档被检索到的比例\n"
        "5. Answer Correctness (答案正确性): 答案与参考答案的匹配度\n"
        "6. Aspect Critique (方面评估): 无害性、帮助性等",
        "Implementation with RAGAS:\n"
        "from ragas import evaluate\n"
        "from ragas.metrics import faithfulness, answer_relevancy\n"
        "result = evaluate(dataset, metrics=[faithfulness, answer_relevancy])\n"
        "Each metric returns a score between 0 and 1.",
        "Best practices:\n"
        "- Use at least 50 test cases for reliable metrics\n"
        "- Include edge cases (empty retrieval, irrelevant context)\n"
        "- Compare with baseline before evaluating improvements\n"
        "- Track metrics over time to detect regressions",
        "Integration with evaluation pipeline:\n"
        "- Run RAGAS metrics as part of CI/CD pipeline\n"
        "- Set minimum thresholds for each metric\n"
        "- Generate detailed reports with failed cases\n"
        "- Use LLM-as-judge for qualitative assessment",
    ])
    msgs.append(_make_tool_result(rag_detail, "web_search", "r6c1"))
    msgs.append(AIMessage(content="RAG 评估的核心指标包括忠实度、答案相关性、上下文精度和召回率。RAGAS 框架提供了现成的实现。"))

    # Round 7: user asks about constraints
    msgs.append(HumanMessage(content="根据前面的讨论，总结一下我们这个项目的主要设计约束是什么？"))
    msgs.append(AIMessage(content="根据前面的讨论，本项目的主要设计约束包括：\n"
                                    "1. 始终使用中文回答\n"
                                    "2. 每次回答需提供引用来源\n"
                                    "3. 不编造数据，优先使用检索信息\n"
                                    "4. 使用 Hermes Agent 四阶段压缩策略\n"
                                    "5. 集成 Milvus 混合检索（稠密+稀疏）\n"
                                    "6. 使用 RAGAS 指标评估系统性能"))

    # Round 8: final question with citation requirement
    msgs.append(HumanMessage(content="请给我一个最终的架构总结，包含你引用的来源"))
    msgs.append(AIMessage(content="## 架构总结\n\n"
                                    "本项目采用 Agentic RAG 架构，核心组件：\n"
                                    "1. **Context Engineering Pipeline** — 基于 Hermes Agent 的四阶段压缩（修剪→边界→摘要→清洗）[来源: Hermes Agent 论文]\n"
                                    "2. **Hybrid Retrieval** — Milvus 稠密+稀疏向量检索 [来源: Milvus 文档]\n"
                                    "3. **Evaluation Framework** — RAGAS 指标 + 自定义评测流程 [来源: RAGAS 论文]\n"
                                    "4. **Multi-Agent Workflow** — Quick/Deep 双链路路由\n\n"
                                    "主要设计约束：中文输出、引用来源、检索优先、自动压缩。"))

    return msgs


def build_huge_conversation() -> list[BaseMessage]:
    """~50 turns with large tool results — guaranteed to compress heavily."""
    msgs: list[BaseMessage] = [
        SystemMessage(
            content="你是 MyPaperWeb 科研助手。\n"
            "约束条件：\n"
            "1. 始终用中文回答\n"
            "2. 每次回答必须提供引用来源\n"
            "3. 不编造数据\n"
            "4. 优先使用检索到的信息而非自身知识\n"
            "5. 保留所有用户提到的约束"
        ),
    ]

    topics = ['Transformer','BERT','GPT','RLHF','LoRA','MoE','Attention','Embedding','Tokenization','Fine-tuning','Prompt Engineering','Chain-of-Thought','Knowledge Distillation','Quantization','Pruning']
    for i in range(15):
        topic = topics[i]
        msgs.append(HumanMessage(content=f"第 {i+1} 轮：搜索关于 {topic} 的最新进展"))
        msgs.append(_make_tool_call("web_search", {"query": f"{topic} 2025 进展"}, f"huge_c{i+1}"))
        # Large tool result ~3000 chars each to exceed 16K trigger
        detail_lines = []
        for j in range(25):
            detail_lines.append(
                f"详细发现 {j+1}: {topic} 在效率优化方面取得了重要进展。"
                f"研究团队提出了新的架构改进方案，在保持效果的同时减少了计算开销。"
                f"实验结果表明，该方法在多个基准测试上取得了最优结果。"
                f"与基线方法相比，性能提升约15-20%，同时参数量减少了30%。"
            )
        detail_block = "\n".join(detail_lines)
        msgs.append(_make_tool_result(
            f"关于 {topic} 的搜索结果：\n{detail_block}\n"
            f"参考链接：https://example.com/{topic.lower()}\n"
            f"相关论文：Paper 2025 on {topic}\n"
            f"作者：团队A, 团队B\n"
            f"发表日期：2025年\n"
            f"关键词：{topic}, 深度学习, 自然语言处理\n"
            f"摘要：本文综述了{topic}领域的最新研究进展。\n",
            "web_search", f"huge_c{i+1}",
        ))
        msgs.append(AIMessage(
            content=f"关于 {topic} 的最新进展：\n"
                    f"该领域在 2025 年有多项重要突破。主要改进集中在效率优化和效果提升两个方面。\n"
                    f"具体来说：(1) 新的架构设计减少了计算复杂度 (2) 训练方法改进提升了模型质量 (3) 推理优化降低了部署成本。\n"
                    f"建议进一步阅读相关论文了解技术细节。"
        ))

    # Final summary that should reference constraints
    msgs.append(HumanMessage(content="请给出所有技术方向的总结对比"))
    msgs.append(AIMessage(content="## 技术总结\n\n以上 15 个方向的对比总结如下：\n"
                                   "Transformer 和 Attention 是基础架构；BERT/GPT 是代表性模型；\n"
                                   "RLHF/LoRA 是微调技术；MoE 是规模化方案；\n"
                                   "Prompt Engineering/CoT 是推理优化；KD/Quantization/Pruning 是模型压缩。\n\n"
                                   "所有以上内容均基于检索结果，遵循中文输出和引用来源的约束。"))
    return msgs


# ---------------------------------------------------------------------------
# content preservation checks
# ---------------------------------------------------------------------------

PRESERVATION_CHECKS = {
    "中文约束": "中文",
    "引用来源约束": "引用",
    "不编造数据约束": "编造",
    "检索优先约束": "检索",
    "Milvus 关键词": "Milvus",
    "RAGAS 关键词": "RAGAS",
    "Hermes 关键词": "Hermes",
    "约束关键词": "约束",
}


def check_content_preservation(
    result_messages: list[BaseMessage],
    checks: dict[str, str] | None = None,
) -> dict[str, bool]:
    """Check if key terms are preserved in the compressed output."""
    if checks is None:
        checks = PRESERVATION_CHECKS
    all_text = " ".join(
        str(getattr(m, "content", "")) for m in result_messages
    )
    return {name: term in all_text for name, term in checks.items()}


# ---------------------------------------------------------------------------
# multi-cycle simulation
# ---------------------------------------------------------------------------

def simulate_multi_cycle(
    service: ContextCompressorService,
    messages: list[BaseMessage],
    cycles: int = 5,
) -> list[dict]:
    """Simulate multiple compression cycles (as in a long-running session)."""
    history: list[dict] = []
    current_messages = list(messages)

    for cycle in range(cycles):
        # Simulate adding a new turn each cycle
        current_messages.append(HumanMessage(
            content=f"第 {cycle+1} 次追加：基于之前的结果，你有什么新的补充吗？"
        ))
        current_messages.append(AIMessage(
            content=f"根据前{cycle+1}轮分析，建议关注以下方面：\n"
                     f"1. 系统的可扩展性\n"
                     f"2. 压缩质量与速度的平衡\n"
                     f"3. 多轮对话中的信息保留\n"
                     f"以上建议基于之前的检索结果。"
        ))

        result = service.compress_messages(current_messages)
        history.append({
            "cycle": cycle + 1,
            "pre_tokens": _total_tokens(current_messages),
            "post_tokens": _total_tokens(result.messages),
            "savings_ratio": result.savings_ratio,
            "was_compressed": result.was_compressed,
            "thrash_warning": result.thrash_warning,
            "message_count": len(result.messages),
            "has_summary": bool(result.summary_text),
        })
        current_messages = result.messages

    return history


# ---------------------------------------------------------------------------
# main benchmark
# ---------------------------------------------------------------------------

def run_benchmark() -> None:
    configs = [
        ("默认配置 (32K/50%)", CompressorConfig(llm_enabled=False)),
        ("紧凑配置 (8K/40%)", CompressorConfig(
            context_window_tokens=8000,
            compression_threshold_ratio=0.4,
            head_protect_messages=3,
            tail_token_budget=4000,
            llm_enabled=False,
        )),
        ("宽松配置 (64K/60%)", CompressorConfig(
            context_window_tokens=64000,
            compression_threshold_ratio=0.6,
            head_protect_messages=5,
            tail_token_budget=30000,
            llm_enabled=False,
        )),
        ("激进配置 (4K/30%)", CompressorConfig(
            context_window_tokens=4000,
            compression_threshold_ratio=0.3,
            head_protect_messages=2,
            tail_token_budget=1000,
            llm_enabled=False,
        )),
    ]

    scenarios = [
        ("简短对话 (5轮)", build_short_conversation()),
        ("长对话 (20轮)", build_long_conversation()),
        ("超长对话 (50轮)", build_huge_conversation()),
    ]

    print("=" * 80)
    print("  上下文压缩基准测试")
    print("=" * 80)

    for scenario_name, scenario_msgs in scenarios:
        print(f"\n{'─' * 80}")
        print(f"  场景: {scenario_name}")
        print(f"  原始消息数: {len(scenario_msgs)}")
        print(f"  原始 Token 数: {_total_tokens(scenario_msgs)}")
        print(f"{'─' * 80}")

        for config_name, config in configs:
            print(f"\n  --- {config_name} ---")

            service = ContextCompressorService(config, llm_factory=None)

            # Single-pass compression
            result = service.compress_messages(scenario_msgs)
            pre = _total_tokens(scenario_msgs)
            post = _total_tokens(result.messages)

            print(f"    压缩前: {pre:>6} tokens")
            print(f"    压缩后: {post:>6} tokens")
            print(f"    节省比例: {result.savings_ratio:>7.1%}")
            print(f"    触发压缩: {result.was_compressed}")
            print(f"    防抖警告: {result.thrash_warning}")

            if result.was_compressed:
                preservation = check_content_preservation(result.messages)
                preserved = sum(1 for v in preservation.values() if v)
                total = len(preservation)
                print(f"    内容保留: {preserved}/{total} 项")
                for check_name, ok in preservation.items():
                    status = "✓" if ok else "✗"
                    print(f"      {status} {check_name}")

            # Multi-cycle simulation
            service.reset()
            cycle_history = simulate_multi_cycle(service, scenario_msgs, cycles=5)
            avg_savings = sum(h["savings_ratio"] for h in cycle_history) / len(cycle_history)
            thrash_count = sum(1 for h in cycle_history if h["thrash_warning"])
            print(f"    5 轮模拟:")
            print(f"      平均节省: {avg_savings:.1%}")
            print(f"      防抖触发: {thrash_count}/5")

    print(f"\n{'=' * 80}")
    print("  基准测试完成")
    print(f"{'=' * 80}")


def run_quick_summary() -> None:
    """Single-pass summary for easy reporting."""
    print("=" * 60)
    print("  上下文压缩快速报告")
    print("=" * 60)

    config = CompressorConfig(llm_enabled=False)
    service = ContextCompressorService(config, llm_factory=None)

    scenarios = [
        ("short", build_short_conversation()),
        ("long", build_long_conversation()),
        ("huge", build_huge_conversation()),
    ]

    for name, msgs in scenarios:
        pre = _total_tokens(msgs)
        result = service.compress_messages(msgs)
        post = _total_tokens(result.messages)

        preservation = {}
        if result.was_compressed:
            preservation = check_content_preservation(result.messages)

        print(f"\n  [{name}]")
        print(f"    messages: {len(msgs):>3} → {len(result.messages):>3}")
        print(f"    tokens:   {pre:>6} → {post:>6}  ({result.savings_ratio:>+.1%})")
        print(f"    compressed={result.was_compressed}  thrash={result.thrash_warning}")
        if preservation:
            preserved_list = [k for k, v in preservation.items() if v]
            print(f"    preserved: {', '.join(preserved_list)}")

        service.reset()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Context compression benchmark")
    parser.add_argument("--quick", action="store_true", help="快速报告模式")
    args = parser.parse_args()

    if args.quick:
        run_quick_summary()
    else:
        run_benchmark()
