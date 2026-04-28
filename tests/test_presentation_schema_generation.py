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


class PresentationSchemaServiceTest(unittest.TestCase):
    def test_build_schema_creates_element_level_structure(self):
        from services.presentation_schema_service import PresentationSchemaService

        service = PresentationSchemaService()
        layout = {
            "title": "Enterprise RAG overview",
            "pages": [
                {
                    "page_index": 1,
                    "purpose": "封面与概览",
                    "topic": "Enterprise RAG overview",
                    "indexes": ["A", "B"],
                    "images": [],
                    "layout": "cover",
                },
                {
                    "page_index": 2,
                    "purpose": "背景与问题",
                    "topic": "Enterprise RAG overview",
                    "indexes": ["Long explanation " * 8, "Second point"],
                    "images": ["figure.png"],
                    "layout": "image_text",
                },
            ],
        }

        schema = service.build_schema(layout)

        self.assertEqual(schema["title"], "Enterprise RAG overview")
        self.assertEqual(len(schema["pages"]), 2)
        first_page = schema["pages"][0]
        self.assertIn("elements", first_page)
        self.assertEqual(first_page["elements"][0]["type"], "title")
        self.assertIn("max_chars", first_page["elements"][0])
        second_types = [item["type"] for item in schema["pages"][1]["elements"]]
        self.assertIn("image", second_types)
        self.assertIn("caption", second_types)
        self.assertIn("bullet", second_types)

    def test_build_schema_filters_noise_and_compresses_long_text(self):
        from services.presentation_schema_service import PresentationSchemaService

        service = PresentationSchemaService()
        layout = {
            "title": "Enterprise RAG overview",
            "pages": [
                {
                    "page_index": 1,
                    "purpose": "背景与问题",
                    "topic": "Enterprise RAG overview",
                    "indexes": ["bridge", "plan", "draft", "{\"debug\": true}", "核心发现"],
                    "images": [],
                    "layout": "single_column_text",
                }
            ],
        }

        schema = service.build_schema(layout)
        texts = [item["text"] for item in schema["pages"][0]["elements"] if "text" in item]

        self.assertTrue(all("bridge" not in text for text in texts))
        self.assertTrue(all("draft" not in text for text in texts))
        self.assertTrue(any("核心发现" in text for text in texts))
        self.assertTrue(all(len(text) <= item["max_chars"] for item in schema["pages"][0]["elements"] if "text" in item for text in [item["text"]]))


if __name__ == "__main__":
    unittest.main()
