"""Quick offline search ranking benchmark — synthetic data, no API calls."""
import sys
from pathlib import Path
_app_dir = str(Path(__file__).parent.parent / "app")
if _app_dir not in sys.path: sys.path.insert(0, _app_dir)

from langchain_core.documents import Document
from services.search_ranking_service import SearchRankingService
from services.source_boost_config import SourceBoostConfig
from services.query_intent_service import QueryIntentService

PAPER_POOL = [
    {"id":"p001","title":"Attention Is All You Need","source":"arxiv","cites":95000,"kw":["attention","transformer"]},
    {"id":"p002","title":"BERT: Pre-training of Deep Bidirectional Transformers","source":"arxiv","cites":75000,"kw":["transformer","pretraining"]},
    {"id":"p003","title":"Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks","source":"arxiv","cites":8000,"kw":["RAG","retrieval","generation"]},
    {"id":"p004","title":"REALM: Retrieval-Augmented Language Model Pre-Training","source":"arxiv","cites":3500,"kw":["retrieval","language model"]},
    {"id":"p005","title":"AgentBench: Evaluating LLMs as Agents","source":"arxiv","cites":1200,"kw":["agent","evaluation","benchmark"]},
    {"id":"p006","title":"Toolformer: Language Models Can Teach Themselves to Use Tools","source":"arxiv","cites":2500,"kw":["tool","planning","agent"]},
    {"id":"p007","title":"LLMLingua: Compressing Prompts for Accelerated Inference","source":"arxiv","cites":800,"kw":["compression","prompt"]},
    {"id":"p008","title":"Selective Context: Context Compression for LLMs","source":"arxiv","cites":450,"kw":["compression","context"]},
    {"id":"p009","title":"LoRA: Low-Rank Adaptation of Large Language Models","source":"arxiv","cites":15000,"kw":["LoRA","fine-tuning","adaptation"]},
    {"id":"p010","title":"Chain-of-Thought Prompting Elicits Reasoning in Large Language Models","source":"arxiv","cites":12000,"kw":["chain of thought","reasoning"]},
    {"id":"p011","title":"Training Language Models to Follow Instructions with Human Feedback","source":"arxiv","cites":18000,"kw":["RLHF","alignment","reinforcement"]},
    {"id":"p012","title":"Denoising Diffusion Probabilistic Models","source":"arxiv","cites":25000,"kw":["diffusion","image generation"]},
    {"id":"p013","title":"Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks","source":"arxiv","cites":20000,"kw":["sentence embedding","contrastive learning"]},
    {"id":"p014","title":"SimCSE: Simple Contrastive Learning of Sentence Embeddings","source":"arxiv","cites":8000,"kw":["contrastive learning","embedding"]},
    {"id":"p015","title":"A Comprehensive Survey on Graph Neural Networks","source":"arxiv","cites":15000,"kw":["GNN","graph neural network","survey"]},
    {"id":"p016","title":"A Survey on Context Compression for Large Language Models","source":"arxiv","cites":300,"kw":["compression","context","survey"]},
    {"id":"p017","title":"FlashAttention: Fast and Memory-Efficient Exact Attention","source":"arxiv","cites":6000,"kw":["attention","efficient","transformer"]},
    {"id":"p018","title":"BLIP-2: Bootstrapping Language-Image Pre-training","source":"arxiv","cites":5000,"kw":["multi-modal","vision-language"]},
    {"id":"p019","title":"Longformer: The Long-Document Transformer","source":"arxiv","cites":9000,"kw":["long context","efficient attention","transformer"]},
]

QUERIES = [
    ("Transformer attention mechanism", ["p001","p002","p017"]),
    ("RAG retrieval augmented generation", ["p003","p004"]),
    ("LLM agent evaluation benchmark", ["p005","p006"]),
    ("context compression survey", ["p007","p008","p016"]),
    ("LoRA fine-tuning efficiency", ["p009"]),
    ("chain of thought reasoning", ["p010"]),
    ("RLHF human feedback alignment", ["p011"]),
    ("diffusion model image generation", ["p012"]),
    ("contrastive learning sentence embedding", ["p013","p014"]),
    ("graph neural network survey", ["p015"]),
]

service = SearchRankingService(
    entity_store=None,
    source_config=SourceBoostConfig(
        source_weights={"papers/": 1.5, "papers/arxiv/": 1.4},
        keyword_boosts={"attention": 1.2, "transformer": 1.2, "RAG": 1.3, "agent": 1.2, "LoRA": 1.2, "diffusion": 1.2, "embedding": 1.1, "compression": 1.2},
    ),
    intent_service=QueryIntentService(),
)

pmap = {p["id"]: p for p in PAPER_POOL}
b3_hits = e3_hits = b5_hits = e5_hits = total = 0
rank_changes = []

print(f"{'Query':<48} {'Expected':<18} {'B@3':>6} {'E@3':>6} {'B@5':>6} {'E@5':>6}")
print("-" * 96)
for q, exp_ids in QUERIES:
    matched = [p for p in PAPER_POOL if any(k in q.lower() for k in p["kw"])]
    if not matched: continue
    base = sorted(matched, key=lambda p: p["cites"], reverse=True)

    docs = [Document(page_content=p["title"], metadata={"_source": f"papers/{p['source']}", "score": min(1.0, p["cites"]/100), "paper_id": p["id"]}) for p in matched]
    boosted = service.apply_boosts(docs, q)
    enhanced = [pmap[d.metadata["paper_id"]] for d in boosted if d.metadata.get("paper_id") in pmap]

    exp = set(exp_ids)
    b3 = sum(1 for p in base[:3] if p["id"] in exp)
    e3 = sum(1 for p in enhanced[:3] if p["id"] in exp)
    b5 = sum(1 for p in base[:5] if p["id"] in exp)
    e5 = sum(1 for p in enhanced[:5] if p["id"] in exp)
    b3_hits += b3; e3_hits += e3; b5_hits += b5; e5_hits += e5; total += len(exp)

    for pid in exp_ids:
        br = next((i for i, p in enumerate(base) if p["id"] == pid), None)
        er = next((i for i, p in enumerate(enhanced) if p["id"] == pid), None)
        if br is not None and er is not None:
            rank_changes.append(br - er)

    print(f"{q:<48} {str(exp_ids):<18} {b3}/{len(exp):>4} {e3}/{len(exp):>4} {b5}/{len(exp):>4} {e5}/{len(exp):>4}")

avg_rc = sum(rank_changes)/len(rank_changes) if rank_changes else 0
print("-" * 96)
print(f"\nTop-3 命中率:  Baseline {b3_hits}/{total} ({b3_hits/total:.1%})  →  Enhanced {e3_hits}/{total} ({e3_hits/total:.1%})  Δ={e3_hits/total - b3_hits/total:+.1%}")
print(f"Top-5 命中率:  Baseline {b5_hits}/{total} ({b5_hits/total:.1%})  →  Enhanced {e5_hits}/{total} ({e5_hits/total:.1%})  Δ={e5_hits/total - b5_hits/total:+.1%}")
print(f"平均排名变化:  {avg_rc:+.2f} (正数 = 提升)")
