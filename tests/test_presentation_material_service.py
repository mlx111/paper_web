import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class PresentationMaterialRequestTest(unittest.TestCase):
    def test_presentation_material_request_accepts_text_and_link_items(self):
        from models.request import PresentationMaterialsRequest

        request = PresentationMaterialsRequest(
            sessionId="presentation-123",
            materials=[
                {
                    "sourceType": "paste",
                    "materialType": "text",
                    "title": "Notes",
                    "content": "Key points",
                    "tags": ["draft"],
                },
                {
                    "sourceType": "link",
                    "materialType": "link",
                    "title": "Reference",
                    "url": "https://example.com",
                },
            ],
        )

        self.assertEqual(request.session_id, "presentation-123")
        self.assertEqual(len(request.materials), 2)
        self.assertEqual(request.materials[0].source_type, "paste")
        self.assertEqual(request.materials[1].url, "https://example.com")


class PresentationMaterialServiceTest(unittest.TestCase):
    def test_save_text_materials_persists_and_lists_entries(self):
        from services.presentation_material_service import PresentationMaterialService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationMaterialService(storage_root=Path(tmp_dir))
            result = service.save_material_entries(
                "presentation-123",
                [
                    {
                        "source_type": "paste",
                        "material_type": "text",
                        "title": "Outline idea",
                        "content": "One, two, three",
                        "tags": ["draft"],
                    },
                    {
                        "source_type": "link",
                        "material_type": "link",
                        "title": "Reference paper",
                        "url": "https://example.com/paper",
                    },
                ],
            )

            self.assertEqual(result["session_id"], "presentation-123")
            self.assertEqual(result["material_count"], 2)
            self.assertTrue(Path(result["materials_path"]).exists())

            loaded = service.load_materials("presentation-123")
            self.assertEqual(len(loaded["materials"]), 2)
            self.assertEqual(loaded["materials"][0]["title"], "Outline idea")
            self.assertEqual(loaded["materials"][1]["url"], "https://example.com/paper")

    def test_save_uploaded_material_writes_file_record(self):
        from services.presentation_material_service import PresentationMaterialService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationMaterialService(storage_root=Path(tmp_dir))
            result = service.save_uploaded_material(
                "presentation-123",
                "reference deck.pptx",
                b"pptx-bytes",
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )

            self.assertEqual(result["session_id"], "presentation-123")
            self.assertTrue(Path(result["file_path"]).exists())
            self.assertEqual(result["material_type"], "document")

            loaded = service.load_materials("presentation-123")
            self.assertEqual(len(loaded["materials"]), 1)
            self.assertEqual(loaded["materials"][0]["material_type"], "document")

    def test_clear_session_materials_removes_storage(self):
        from services.presentation_material_service import PresentationMaterialService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationMaterialService(storage_root=Path(tmp_dir))
            service.save_material_entries(
                "presentation-123",
                [
                    {
                        "source_type": "paste",
                        "material_type": "text",
                        "title": "Note",
                        "content": "hello",
                    }
                ],
            )

            self.assertTrue(service.clear_session_materials("presentation-123"))
            self.assertEqual(service.load_materials("presentation-123")["material_count"], 0)


if __name__ == "__main__":
    unittest.main()
