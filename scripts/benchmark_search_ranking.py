#!/usr/bin/env python3
"""Parallel benchmark: compare baseline vs enhanced search ranking on academic queries.

Runs searches concurrently via thread pool, then evaluates baseline vs enhanced ranking.

Usage:
    python scripts/benchmark_search_ranking.py [--workers 5]
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from services.academic_tools_service import academic_tools_service
from services.entity_extraction_singletons import entity_link_store
from services.search_ranking_singletons import search_ranking_service

TEST_CASES: list[dict[str, Any]] = [
    {"id": "s001", "query": "RAG evaluation metrics", "terms_loose": ["evaluation", "metrics", "RAG"], "terms_strict": ["evaluation metrics", "RAG"], "expected_papers": ["Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"]},
    {"id": "s002", "query": "chain of thought reasoning", "terms_loose": ["chain-of-thought", "reasoning", "prompt"], "terms_strict": ["chain of thought"], "expected_papers": ["Chain-of-Thought Prompting Elicits Reasoning in Large Language Models"]},
    {"id": "s003", "query": "large language model alignment", "terms_loose": ["alignment", "RLHF", "constitutional"], "terms_strict": ["alignment", "RLHF"], "expected_papers": ["Training Language Models to Follow Instructions with Human Feedback"]},
    {"id": "s004", "query": "graph neural network molecular", "terms_loose": ["graph", "molecular", "property"], "terms_strict": ["graph neural", "molecular"], "expected_papers": []},
    {"id": "s005", "query": "diffusion model image generation", "terms_loose": ["diffusion", "image", "generation"], "terms_strict": ["diffusion model", "image generation"], "expected_papers": ["Denoising Diffusion Probabilistic Models"]},
    {"id": "s006", "query": "transformer attention mechanism efficient", "terms_loose": ["attention", "transformer", "efficient"], "terms_strict": ["attention mechanism", "transformer"], "expected_papers": ["Attention Is All You Need"]},
    {"id": "s007", "query": "reinforcement learning human feedback", "terms_loose": ["RLHF", "reinforcement", "feedback"], "terms_strict": ["reinforcement learning", "human feedback"], "expected_papers": ["Training Language Models to Follow Instructions with Human Feedback"]},
    {"id": "s008", "query": "multimodal learning vision language", "terms_loose": ["multimodal", "vision", "language"], "terms_strict": ["multimodal", "vision language"], "expected_papers": ["BLIP-2: Bootstrapping Language-Image Pre-training"]},
    {"id": "s009", "query": "few-shot learning meta learning", "terms_loose": ["few-shot", "meta-learning", "generalization"], "terms_strict": ["few-shot", "meta learning"], "expected_papers": []},
    {"id": "s010", "query": "knowledge graph embedding link prediction", "terms_loose": ["embedding", "link prediction", "knowledge"], "terms_strict": ["knowledge graph", "link prediction"], "expected_papers": []},
    {"id": "s011", "query": "neural machine translation low resource", "terms_loose": ["translation", "low-resource", "neural"], "terms_strict": ["neural machine translation", "low resource"], "expected_papers": []},
    {"id": "s012", "query": "contrastive learning representation", "terms_loose": ["contrastive", "representation", "self-supervised"], "terms_strict": ["contrastive learning", "representation learning"], "expected_papers": ["SimCSE: Simple Contrastive Learning of Sentence Embeddings"]},
    {"id": "s013", "query": "adversarial robustness deep learning", "terms_loose": ["adversarial", "robustness", "attack"], "terms_strict": ["adversarial robustness", "adversarial attack"], "expected_papers": []},
    {"id": "s014", "query": "quantization compression large language model", "terms_loose": ["quantization", "compression", "pruning"], "terms_strict": ["model quantization", "model compression"], "expected_papers": ["LLMLingua: Compressing Prompts for Accelerated Inference"]},
    {"id": "s015", "query": "multi-agent reinforcement learning", "terms_loose": ["multi-agent", "cooperation", "communication"], "terms_strict": ["multi-agent", "cooperation"], "expected_papers": []},
    {"id": "s016", "query": "preference optimization LLM DPO", "terms_loose": ["preference", "optimization", "DPO"], "terms_strict": ["preference optimization", "DPO"], "expected_papers": []},
    {"id": "s017", "query": "LoRA fine-tuning large language model", "terms_loose": ["LoRA", "fine-tuning", "efficient"], "terms_strict": ["LoRA", "parameter efficient"], "expected_papers": ["LoRA: Low-Rank Adaptation of Large Language Models"]},
    {"id": "s018", "query": "mixture of experts MoE sparse model", "terms_loose": ["mixture of experts", "MoE", "sparse"], "terms_strict": ["mixture of experts", "sparse"], "expected_papers": []},
    {"id": "s019", "query": "speculative decoding LLM inference", "terms_loose": ["speculative decoding", "inference", "acceleration"], "terms_strict": ["speculative decoding", "inference"], "expected_papers": []},
    {"id": "s020", "query": "retrieval augmented generation RAG", "terms_loose": ["RAG", "knowledge", "retrieval"], "terms_strict": ["retrieval augmented", "knowledge"], "expected_papers": ["Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"]},
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _term_in_paper(term: str, paper: dict[str, Any]) -> bool:
    t = term.lower()
    title = str(paper.get("title", "")).lower()
    abstract = str(paper.get("abstract", "")).lower()
    return t in title or t in abstract


def _paper_title_in_results(title: str, papers: list[dict[str, Any]]) -> int | None:
    t = title.lower().strip()
    for rank, p in enumerate(papers, 1):
        pt = str(p.get("title", "")).lower().strip()
        if t == pt or pt.startswith(t) or t.startswith(pt):
            return rank
    return None


def _eval_case(
    papers: list[dict[str, Any]],
    terms_loose: list[str],
    terms_strict: list[str],
    expected_papers: list[str],
    k_values: list[int],
) -> dict[str, Any]:
    loose_hits: dict[int, bool] = {}
    strict_hits: dict[int, bool] = {}
    paper_ranks: dict[str, int | None] = {t: None for t in expected_papers}
    loose_found: set[int] = set()
    strict_found: set[int] = set()
    sorted_k = sorted(k_values)

    for rank, paper in enumerate(papers, 1):
        for ti, term in enumerate(terms_loose):
            if _term_in_paper(term, paper):
                loose_found.add(ti)
        for ti, term in enumerate(terms_strict):
            if _term_in_paper(term, paper):
                strict_found.add(ti)
        for k in sorted_k:
            if rank == k:
                loose_hits[k] = len(loose_found) > 0
                strict_hits[k] = len(strict_found) == len(terms_strict)

    # If fewer than k results were returned, treat Top-k as "all available results so far".
    for k in sorted_k:
        if k not in loose_hits:
            loose_hits[k] = len(loose_found) > 0
            strict_hits[k] = len(strict_found) == len(terms_strict)

    for t in expected_papers:
        r = _paper_title_in_results(t, papers)
        if r is not None:
            paper_ranks[t] = r
    return {
        "loose_evidence_hit": any(loose_hits.get(k, False) for k in k_values),
        "strict_all_hit": any(strict_hits.get(k, False) for k in k_values),
        "loose_hit_at_k": {str(k): loose_hits.get(k, False) for k in k_values},
        "strict_hit_at_k": {str(k): strict_hits.get(k, False) for k in k_values},
        "paper_ranks": paper_ranks,
    }


def _search_one(case: dict[str, Any], result_limit: int) -> dict[str, Any]:
    """Search for one case (runs in thread pool)."""
    try:
        raw = academic_tools_service.search_papers(
            case["query"], result_limit=result_limit, engine="auto", apply_ranking=False,
        )
        papers = list(raw.get("papers", []))
        return {"id": case["id"], "papers": papers, "error": None}
    except Exception as e:
        return {"id": case["id"], "papers": [], "error": str(e)}


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    cases: list[dict[str, Any]],
    k_values: list[int] | None = None,
    result_limit: int = 5,
    workers: int = 5,
) -> dict[str, Any]:
    if k_values is None:
        k_values = [3, 5]

    print(f"  Searching {len(cases)} queries with {workers} workers...")
    t0 = time.time()
    search_results: dict[str, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_search_one, c, result_limit): c["id"] for c in cases}
        done = 0
        for f in as_completed(futures):
            done += 1
            r = f.result()
            search_results[r["id"]] = r["papers"]
            status = "ERR" if r["error"] else f"{len(r['papers'])} papers"
            print(f"    [{done}/{len(cases)}] {r['id']}: {status}")

    t1 = time.time()
    print(f"  Search done in {t1-t0:.1f}s. Evaluating ranking...")

    # Evaluate (sequential, no I/O)
    per_case: list[dict[str, Any]] = []
    for case in cases:
        cid = case["id"]
        query = case["query"]
        baseline_papers = search_results.get(cid, [])

        baseline_eval = _eval_case(
            baseline_papers, case.get("terms_loose", []),
            case.get("terms_strict", []), case.get("expected_papers", []), k_values,
        )
        enhanced_papers = list(search_ranking_service.rank_papers_dicts(baseline_papers, query))
        enhanced_eval = _eval_case(
            enhanced_papers, case.get("terms_loose", []),
            case.get("terms_strict", []), case.get("expected_papers", []), k_values,
        )

        improved = any(
            enhanced_eval.get("loose_hit_at_k", {}).get(str(k), False)
            and not baseline_eval.get("loose_hit_at_k", {}).get(str(k), False)
            or enhanced_eval.get("strict_hit_at_k", {}).get(str(k), False)
            and not baseline_eval.get("strict_hit_at_k", {}).get(str(k), False)
            for k in k_values
        )
        per_case.append({
            "id": cid, "query": query, "num_results": len(baseline_papers),
            "expected_papers": list(case.get("expected_papers", [])),
            "baseline": baseline_eval, "enhanced": enhanced_eval, "improved": improved,
        })

    n = len(per_case)
    agg: dict[str, Any] = {
        "total_cases": n, "k_values": k_values,
        "search_time_s": round(t1 - t0, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for mode, key in [("loose", "loose_hit_at_k"), ("strict", "strict_hit_at_k")]:
        for k in k_values:
            bh = sum(1 for c in per_case if c["baseline"][key].get(str(k), False))
            eh = sum(1 for c in per_case if c["enhanced"][key].get(str(k), False))
            agg[f"baseline_{mode}_top{k}_hit_rate"] = round(bh / n, 3)
            agg[f"enhanced_{mode}_top{k}_hit_rate"] = round(eh / n, 3)
            agg[f"{mode}_top{k}_delta"] = round((eh - bh) / n, 3)

    be = sum(1 for c in per_case if c["baseline"]["loose_evidence_hit"])
    ee = sum(1 for c in per_case if c["enhanced"]["loose_evidence_hit"])
    agg["baseline_evidence_hit_rate"] = round(be / n, 3)
    agg["enhanced_evidence_hit_rate"] = round(ee / n, 3)
    agg["evidence_delta"] = round((ee - be) / n, 3)

    bs = sum(1 for c in per_case if c["baseline"]["strict_all_hit"])
    es = sum(1 for c in per_case if c["enhanced"]["strict_all_hit"])
    agg["baseline_strict_hit_rate"] = round(bs / n, 3)
    agg["enhanced_strict_hit_rate"] = round(es / n, 3)
    agg["strict_delta"] = round((es - bs) / n, 3)

    paper_count = sum(len(c.get("expected_papers", [])) for c in cases)
    b_mrr = sum(
        1.0 / c["baseline"]["paper_ranks"][t]
        for c in per_case for t in c.get("expected_papers", [])
        if c["baseline"]["paper_ranks"].get(t)
    )
    e_mrr = sum(
        1.0 / c["enhanced"]["paper_ranks"][t]
        for c in per_case for t in c.get("expected_papers", [])
        if c["enhanced"]["paper_ranks"].get(t)
    )
    agg["baseline_mrr"] = round(b_mrr / max(paper_count, 1), 3)
    agg["enhanced_mrr"] = round(e_mrr / max(paper_count, 1), 3)
    agg["mrr_delta"] = round((e_mrr - b_mrr) / max(paper_count, 1), 3)
    agg["entity_store"] = {"entities": entity_link_store.entity_count, "links": entity_link_store.link_count}
    agg["improved_count"] = sum(1 for c in per_case if c["improved"])
    agg["unchanged_count"] = n - agg["improved_count"]

    return {"summary": agg, "cases": per_case}


def write_report(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    s = result["summary"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = output_dir / f"benchmark_search_ranking_{ts}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = output_dir / f"benchmark_search_ranking_{ts}.md"
    lines = [
        "# 检索排序 Benchmark 报告",
        "",
        f"生成时间: {s['timestamp']}",
        f"测试用例数: {s['total_cases']}",
        f"检索耗时: {s['search_time_s']}s",
        f"实体图: {s['entity_store']['entities']} entities, {s['entity_store']['links']} links",
        "",
        "## 聚合指标",
        "",
        "| 指标 | Baseline | Enhanced | Δ |",
        "|------|----------|----------|-----|",
    ]
    for mk, ml in [("loose_top3", "Loose Hit@3"), ("loose_top5", "Loose Hit@5"),
                   ("strict_top3", "Strict All@3"), ("strict_top5", "Strict All@5")]:
        bk = s.get(f"baseline_{mk}_hit_rate", 0)
        ek = s.get(f"enhanced_{mk}_hit_rate", 0)
        dk = s.get(f"{mk}_delta", 0)
        lines.append(f"| {ml} | {bk:.1%} | {ek:.1%} | {dk:+.1%} |")

    lines.append(f"| Evidence Hit | {s['baseline_evidence_hit_rate']:.1%} | {s['enhanced_evidence_hit_rate']:.1%} | {s['evidence_delta']:+.1%} |")
    lines.append(f"| Strict All-Hit | {s['baseline_strict_hit_rate']:.1%} | {s['enhanced_strict_hit_rate']:.1%} | {s['strict_delta']:+.1%} |")
    lines.append(f"| Expected Paper MRR | {s['baseline_mrr']:.3f} | {s['enhanced_mrr']:.3f} | {s['mrr_delta']:+.3f} |")
    lines.append("")
    lines.append(f"**改进**: {s['improved_count']} / **不变**: {s['unchanged_count']}")
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--output", type=str, default=str(PROJECT_ROOT / "app" / "data" / "evaluation"))
    args = parser.parse_args()

    print(f"Running benchmark: {len(TEST_CASES)} cases, {args.workers} workers\n")
    result = run_benchmark(TEST_CASES, workers=args.workers)
    paths = write_report(result, args.output)
    s = result["summary"]

    print("\n========== Summary ==========")
    print(f"  Cases:  {s['total_cases']}  (search: {s['search_time_s']}s)")
    for mode in ["loose", "strict"]:
        for k in [3, 5]:
            bk = s.get(f"baseline_{mode}_top{k}_hit_rate", 0)
            ek = s.get(f"enhanced_{mode}_top{k}_hit_rate", 0)
            dk = s.get(f"{mode}_top{k}_delta", 0)
            print(f"  {mode} Top-{k}: {bk:.1%} -> {ek:.1%}  (d={dk:+.1%})")
    print(f"  MRR:              {s['baseline_mrr']:.3f} -> {s['enhanced_mrr']:.3f}  (d={s['mrr_delta']:+.3f})")
    print(f"  Strict all-hit:   {s['baseline_strict_hit_rate']:.1%} -> {s['enhanced_strict_hit_rate']:.1%}")
    print(f"  Improved:         {s['improved_count']}/{s['total_cases']}")
    print(f"  Entity store:     {s['entity_store']['entities']} entities, {s['entity_store']['links']} links")
    print()
    print(f"  JSON:     {paths['json']}")
    print(f"  Markdown: {paths['markdown']}")
