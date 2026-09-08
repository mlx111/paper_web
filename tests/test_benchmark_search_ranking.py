from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "benchmark_search_ranking.py"


def _load_benchmark_module():
    module_name = "benchmark_search_ranking_for_test"
    academic_tools_module = types.ModuleType("services.academic_tools_service")
    academic_tools_module.academic_tools_service = types.SimpleNamespace(search_papers=lambda *args, **kwargs: {"papers": []})

    entity_module = types.ModuleType("services.entity_extraction_singletons")
    entity_module.entity_link_store = types.SimpleNamespace(entity_count=0, link_count=0)

    ranking_module = types.ModuleType("services.search_ranking_singletons")
    ranking_module.search_ranking_service = types.SimpleNamespace(rank_papers_dicts=lambda papers, query: papers)

    originals = {
        "services.academic_tools_service": sys.modules.get("services.academic_tools_service"),
        "services.entity_extraction_singletons": sys.modules.get("services.entity_extraction_singletons"),
        "services.search_ranking_singletons": sys.modules.get("services.search_ranking_singletons"),
    }
    sys.modules["services.academic_tools_service"] = academic_tools_module
    sys.modules["services.entity_extraction_singletons"] = entity_module
    sys.modules["services.search_ranking_singletons"] = ranking_module

    try:
        spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class BenchmarkSearchRankingEvalCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_benchmark_module()

    def test_loose_topk_counts_hits_within_prefix(self):
        papers = [
            {"title": "Paper A", "abstract": "irrelevant"},
            {"title": "Paper B", "abstract": "contains target term"},
            {"title": "Paper C", "abstract": "irrelevant"},
        ]

        result = self.module._eval_case(
            papers=papers,
            terms_loose=["target term"],
            terms_strict=["target term"],
            expected_papers=[],
            k_values=[3],
        )

        self.assertTrue(result["loose_hit_at_k"]["3"])
        self.assertTrue(result["strict_hit_at_k"]["3"])

    def test_topk_can_stay_true_even_if_rank_k_item_is_not_a_hit(self):
        papers = [
            {"title": "Paper A", "abstract": "contains target term"},
            {"title": "Paper B", "abstract": "irrelevant"},
            {"title": "Paper C", "abstract": "irrelevant"},
            {"title": "Paper D", "abstract": "irrelevant"},
            {"title": "Paper E", "abstract": "irrelevant"},
        ]

        result = self.module._eval_case(
            papers=papers,
            terms_loose=["target term"],
            terms_strict=["target term"],
            expected_papers=[],
            k_values=[3, 5],
        )

        self.assertTrue(result["loose_hit_at_k"]["3"])
        self.assertTrue(result["strict_hit_at_k"]["3"])
        self.assertTrue(result["loose_hit_at_k"]["5"])
        self.assertTrue(result["strict_hit_at_k"]["5"])

    def test_run_benchmark_includes_expected_papers_and_computes_mrr(self):
        cases = [
            {
                "id": "c1",
                "query": "query one",
                "terms_loose": ["target"],
                "terms_strict": ["target"],
                "expected_papers": ["Paper B"],
            }
        ]
        baseline_papers = [
            {"title": "Paper A", "abstract": "irrelevant", "source": "arxiv", "citation_count": 500},
            {"title": "Paper B", "abstract": "contains target", "source": "arxiv", "citation_count": 100},
        ]
        enhanced_papers = [
            {"title": "Paper B", "abstract": "contains target", "source": "arxiv", "citation_count": 100},
            {"title": "Paper A", "abstract": "irrelevant", "source": "arxiv", "citation_count": 500},
        ]

        original_search_one = self.module._search_one
        original_rank = self.module.search_ranking_service.rank_papers_dicts
        try:
            self.module._search_one = lambda case, result_limit: {"id": case["id"], "papers": baseline_papers, "error": None}
            self.module.search_ranking_service.rank_papers_dicts = lambda papers, query: enhanced_papers

            result = self.module.run_benchmark(cases, k_values=[3, 5], result_limit=5, workers=1)
        finally:
            self.module._search_one = original_search_one
            self.module.search_ranking_service.rank_papers_dicts = original_rank

        self.assertEqual(result["cases"][0]["expected_papers"], ["Paper B"])
        self.assertEqual(result["cases"][0]["baseline"]["paper_ranks"]["Paper B"], 2)
        self.assertEqual(result["cases"][0]["enhanced"]["paper_ranks"]["Paper B"], 1)
        self.assertEqual(result["summary"]["baseline_mrr"], 0.5)
        self.assertEqual(result["summary"]["enhanced_mrr"], 1.0)
        self.assertEqual(result["summary"]["mrr_delta"], 0.5)


if __name__ == "__main__":
    unittest.main()
