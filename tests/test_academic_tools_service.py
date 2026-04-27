import json
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
import types


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class AcademicToolsServiceTest(unittest.TestCase):
    def test_search_papers_openalex_formats_results(self):
        from services.academic_tools_service import AcademicToolsService

        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {
            "results": [
                {
                    "title": "Agentic RAG for Papers",
                    "abstract_inverted_index": {
                        "Agentic": [0],
                        "RAG": [1],
                        "helps": [2],
                    },
                    "authorships": [
                        {"author": {"display_name": "Ada Lovelace"}},
                        {"author": {"display_name": "Alan Turing"}},
                    ],
                    "primary_location": {
                        "source": {"display_name": "AI Journal"},
                        "landing_page_url": "https://example.com/paper",
                    },
                    "publication_year": 2026,
                    "cited_by_count": 12,
                    "doi": "https://doi.org/10.1234/example",
                    "id": "https://openalex.org/W123",
                }
            ]
        }
        http_get = Mock(return_value=response)

        service = AcademicToolsService(http_get=http_get)
        result = service.search_papers("agent rag", result_limit=1, engine="openalex")

        self.assertTrue(result["ok"])
        self.assertEqual(result["num_results"], 1)
        paper = result["papers"][0]
        self.assertEqual(paper["title"], "Agentic RAG for Papers")
        self.assertEqual(paper["abstract"], "Agentic RAG helps")
        self.assertEqual(paper["authors"], "Ada Lovelace, Alan Turing")
        self.assertEqual(paper["venue"], "AI Journal")
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["citation_count"], 12)
        self.assertIn("Agentic RAG for Papers", result["formatted"])

    def test_get_bibtex_from_arxiv_url_uses_arxiv_doi(self):
        from services.academic_tools_service import AcademicToolsService

        response = Mock()
        response.status_code = 200
        response.text = "@article{vaswani2017attention,title={Attention Is All You Need}}"
        http_get = Mock(return_value=response)

        service = AcademicToolsService(http_get=http_get)
        result = service.get_bibtex_from_url(
            "https://arxiv.org/abs/1706.03762v2",
            "Attention Is All You Need",
        )

        self.assertTrue(result["ok"])
        self.assertIn("@article", result["bibtex"])
        called_url = http_get.call_args.args[0]
        self.assertEqual(called_url, "https://doi.org/10.48550/arXiv.1706.03762")

    def test_academic_search_tool_compacts_large_payload_for_agent_context(self):
        original_loguru = sys.modules.get("loguru")
        original_langchain_tools = sys.modules.get("langchain_core.tools")
        sys.modules["loguru"] = types.SimpleNamespace(
            logger=types.SimpleNamespace(error=lambda *args, **kwargs: None)
        )
        sys.modules["langchain_core.tools"] = types.SimpleNamespace(
            tool=lambda *args, **kwargs: (lambda fn: types.SimpleNamespace(invoke=lambda payload: fn(**payload)))
        )

        module_path = APP_DIR / "tools" / "academic_tool.py"
        spec = importlib.util.spec_from_file_location("test_academic_tool_module", module_path)
        academic_tool = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(academic_tool)

        original_search = academic_tool.academic_tools_service.search_papers
        academic_tool.academic_tools_service.search_papers = Mock(
            return_value={
                "ok": True,
                "query": "agent",
                "engine": "openalex",
                "num_results": 10,
                "papers": [
                    {
                        "title": "Paper A",
                        "authors": "Ada",
                        "venue": "AIConf",
                        "year": 2026,
                        "citation_count": 10,
                        "url": "https://example.com/a",
                        "abstract": "A" * 600,
                    },
                    {
                        "title": "Paper B",
                        "authors": "Bob",
                        "venue": "AIConf",
                        "year": 2025,
                        "citation_count": 8,
                        "url": "https://example.com/b",
                        "abstract": "B" * 80,
                    },
                    {
                        "title": "Paper C",
                        "authors": "Carol",
                        "venue": "AIConf",
                        "year": 2024,
                        "citation_count": 5,
                        "url": "https://example.com/c",
                        "abstract": "C" * 80,
                    },
                    {
                        "title": "Paper D",
                        "authors": "Dan",
                        "venue": "AIConf",
                        "year": 2023,
                        "citation_count": 3,
                        "url": "https://example.com/d",
                        "abstract": "D" * 80,
                    },
                ],
            }
        )

        try:
            payload = json.loads(academic_tool.academic_search_papers.invoke({"query": "agent", "result_limit": 10}))
        finally:
            academic_tool.academic_tools_service.search_papers = original_search
            if original_loguru is None:
                sys.modules.pop("loguru", None)
            else:
                sys.modules["loguru"] = original_loguru
            if original_langchain_tools is None:
                sys.modules.pop("langchain_core.tools", None)
            else:
                sys.modules["langchain_core.tools"] = original_langchain_tools

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["papers"]), 3)
        self.assertNotIn("formatted", payload)
        self.assertLessEqual(len(payload["papers"][0]["abstract"]), 283)
        self.assertIn("summary", payload)


if __name__ == "__main__":
    unittest.main()
