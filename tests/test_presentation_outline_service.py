import json
import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

STUB_MODULES = ["loguru"]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in STUB_MODULES}

for name in STUB_MODULES:
    sys.modules.setdefault(name, types.ModuleType(name))

sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class PresentationOutlineServiceTest(unittest.TestCase):
    def test_build_outline_filters_noise_and_keeps_structure(self):
        from services.presentation_outline_service import PresentationOutlineService

        service = PresentationOutlineService()
        outline = service.build_outline(
            topic="Enterprise RAG overview",
            gathered=[
                {
                    "title": "Research process",
                    "snippet": "bridge\nplan\ndraft\n{\"debug\": true}\n核心发现",
                },
                {
                    "title": "User note",
                    "snippet": "用户提供的要点",
                },
            ],
            target_pages=4,
        )

        self.assertEqual(outline["title"], "Enterprise RAG overview")
        self.assertEqual(len(outline["pages"]), 4)
        first_page = outline["pages"][0]
        self.assertIn("purpose", first_page)
        self.assertIn("topic", first_page)
        self.assertIn("indexes", first_page)
        self.assertIn("images", first_page)

        outline_text = json.dumps(outline, ensure_ascii=False)
        self.assertNotIn("bridge", outline_text)
        self.assertNotIn("draft", outline_text)
        self.assertNotIn("{\"debug\": true}", outline_text)
        self.assertIn("用户提供的要点", outline_text)

    def test_outline_can_be_converted_to_plan(self):
        from services.presentation_outline_service import PresentationOutlineService

        service = PresentationOutlineService()
        outline = {
            "title": "Enterprise RAG overview",
            "pages": [
                {"page_index": 1, "purpose": "封面", "topic": "Enterprise RAG overview", "indexes": ["A"], "images": []},
                {"page_index": 2, "purpose": "背景", "topic": "Enterprise RAG overview", "indexes": ["B"], "images": []},
            ],
        }

        plan = service.outline_to_plan(outline)

        self.assertEqual(plan["title"], "Enterprise RAG overview")
        self.assertEqual(len(plan["slides"]), 2)
        self.assertEqual(plan["slides"][0]["title"], "封面")
        self.assertIn("A", plan["slides"][0]["bullets"][0])


if __name__ == "__main__":
    unittest.main()
