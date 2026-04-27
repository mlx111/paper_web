import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class DocumentParserServiceTest(unittest.TestCase):
    def test_extract_text_from_txt_returns_summary_and_counts(self):
        from services.document_parser_service import DocumentParserService

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "note.txt"
            path.write_text("第一段内容。\n第二段内容包含 MyPaperWeb。", encoding="utf-8")

            result = DocumentParserService(allowed_roots=[Path(temp_dir)]).extract_text_from_file(
                str(path), summary_length=8
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["file_type"], ".txt")
        self.assertIn("MyPaperWeb", result["text"])
        self.assertLessEqual(len(result["summary"]), 11)
        self.assertEqual(result["char_count"], len(result["text"]))

    def test_extract_text_from_html_strips_tags(self):
        from services.document_parser_service import DocumentParserService

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "paper.html"
            path.write_text(
                "<html><head><style>.x{}</style></head><body><h1>标题</h1><p>正文内容</p></body></html>",
                encoding="utf-8",
            )

            result = DocumentParserService(allowed_roots=[Path(temp_dir)]).extract_text_from_file(str(path))

        self.assertTrue(result["ok"])
        self.assertEqual(result["file_type"], ".html")
        self.assertIn("标题", result["text"])
        self.assertIn("正文内容", result["text"])
        self.assertNotIn("<p>", result["text"])

    def test_rejects_path_outside_allowed_roots(self):
        from services.document_parser_service import DocumentParserService

        result = DocumentParserService(allowed_roots=[Path.cwd() / "uploads"]).extract_text_from_file(
            str(Path.cwd().parent / "outside.txt")
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "PATH_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
