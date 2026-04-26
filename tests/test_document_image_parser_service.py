import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class DocumentImageParserServiceTest(unittest.TestCase):
    def test_parse_docx_saves_images_and_inserts_placeholders(self):
        from services.chunk_image_store_service import ChunkImageStore
        from services.document_image_parser_service import DocumentImageParserService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docx_path = root / "paper.docx"
            _write_minimal_docx_with_image(docx_path)

            store = ChunkImageStore(root / "images", root / "chunk_images.json")
            parser = DocumentImageParserService(image_store=store, chunk_size=200, chunk_overlap=0)

            parsed_docs = parser.parse(str(docx_path), "paper.docx")

            self.assertEqual(len(parsed_docs), 1)
            content = parsed_docs[0].page_content
            self.assertIn("图 1 展示了整体结构。", content)
            self.assertIn("图片下方继续说明。", content)
            self.assertRegex(content, r"<<IMAGE:[0-9a-f]{8}>>")
            self.assertEqual(parsed_docs[0].metadata["chunk_level"], 3)

            placeholder = parsed_docs[0].metadata["image_placeholders"][0]
            image_map = store.resolve_image_map([placeholder])
            self.assertEqual(list(image_map), [placeholder])


def _write_minimal_docx_with_image(path: Path) -> None:
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00"
        b"\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:r><w:t>图 1 展示了整体结构。</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><a:blip r:embed="rId1" /></w:drawing></w:r></w:p>
    <w:p><w:r><w:t>图片下方继续说明。</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        zf.writestr("word/media/image1.png", png_bytes)


if __name__ == "__main__":
    unittest.main()
