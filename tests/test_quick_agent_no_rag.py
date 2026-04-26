from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QuickAgentNoRagTest(unittest.TestCase):
    def test_agent_router_uses_quick_agent_directly(self):
        source = (PROJECT_ROOT / "app" / "routers" / "agent.py").read_text(encoding="utf-8")

        self.assertIn("from agents.quick_agent_service import quick_agent_service as agent_service", source)
        self.assertNotIn("from agents.router_agent_service import agent_service", source)

    def test_quick_agent_does_not_register_rag_tool(self):
        source = (PROJECT_ROOT / "app" / "agents" / "quick_agent_service.py").read_text(encoding="utf-8")

        self.assertNotIn("retrieve_knowledge", source)
        self.assertIn("def _retrieve_context_documents", source)
        self.assertIn("return []", source)


if __name__ == "__main__":
    unittest.main()
