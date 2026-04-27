import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class _AcademicServiceStub:
    def search_papers(self, query, result_limit=5, engine="openalex"):
        return {
            "ok": True,
            "papers": [
                {
                    "title": "Agentic RAG Evaluation",
                    "authors": "Ada Lovelace",
                    "year": 2026,
                    "venue": "AI Journal",
                    "abstract": "A paper about evaluating agentic RAG systems.",
                    "url": "https://arxiv.org/abs/2601.00001",
                }
            ],
        }

    def get_bibtex_from_url(self, url, title):
        return {"ok": True, "bibtex": "@article{agentic2026,title={Agentic RAG Evaluation}}"}


class PaperRefinerServiceTest(unittest.TestCase):
    def test_review_paper_quality_returns_structured_review(self):
        from services.paper_refiner_service import PaperRefinerService

        paper_text = """
        Abstract: We study agentic RAG systems.
        Introduction: Retrieval augmented generation is widely used.
        Method: We propose a workflow-based agent architecture.
        Experiments: We compare accuracy and latency on benchmark tasks.
        Conclusion: The method improves traceability.
        References: [1] Prior RAG work.
        """

        result = PaperRefinerService().review_paper_quality(paper_text, title="Agentic RAG")

        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "Agentic RAG")
        self.assertIn("novelty", result["review"])
        self.assertIn("strengths", result["review"])
        self.assertIn("weaknesses", result["review"])
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 10)

    def test_build_citation_pool_uses_academic_search_and_bibtex(self):
        from services.paper_refiner_service import PaperRefinerService

        service = PaperRefinerService(academic_service=_AcademicServiceStub())
        result = service.build_citation_pool(
            topic="agentic rag evaluation",
            max_papers=1,
            include_bibtex=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        citation = result["citations"][0]
        self.assertEqual(citation["title"], "Agentic RAG Evaluation")
        self.assertIn("@article", citation["bibtex"])


if __name__ == "__main__":
    unittest.main()
