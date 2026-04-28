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


class PresentationLayoutSelectorTest(unittest.TestCase):
    def test_selects_expected_layouts_for_different_page_shapes(self):
        from services.presentation_layout_service import PresentationLayoutService

        service = PresentationLayoutService()
        outline = {
            "title": "Enterprise RAG overview",
            "pages": [
                {"page_index": 1, "purpose": "封面与概览", "topic": "Enterprise RAG overview", "indexes": ["A"], "images": []},
                {
                    "page_index": 2,
                    "purpose": "背景与问题",
                    "topic": "Enterprise RAG overview",
                    "indexes": ["Long explanation " * 10],
                    "images": [],
                },
                {
                    "page_index": 3,
                    "purpose": "核心观点",
                    "topic": "Enterprise RAG overview",
                    "indexes": ["Left column", "Right column", "Another point"],
                    "images": ["figure.png"],
                },
                {
                    "page_index": 4,
                    "purpose": "总结与展望",
                    "topic": "Enterprise RAG overview",
                    "indexes": ["One", "Two"],
                    "images": [],
                },
            ],
        }

        selected = service.select_layouts(outline)

        self.assertEqual(selected["pages"][0]["layout"], "cover")
        self.assertEqual(selected["pages"][1]["layout"], "single_column_text")
        self.assertEqual(selected["pages"][2]["layout"], "image_text")
        self.assertEqual(selected["pages"][3]["layout"], "closing")
        self.assertIn("reason", selected["pages"][2])

    def test_layout_service_marks_dense_pages_as_two_column(self):
        from services.presentation_layout_service import PresentationLayoutService

        service = PresentationLayoutService()
        page = {
            "page_index": 2,
            "purpose": "背景与问题",
            "topic": "Enterprise RAG overview",
            "indexes": ["A", "B", "C", "D", "E"],
            "images": [],
        }

        layout = service.select_layout_for_page(page, is_first=False, is_last=False)

        self.assertEqual(layout["layout"], "two_column")
        self.assertIn("dense", layout["reason"])


if __name__ == "__main__":
    unittest.main()
