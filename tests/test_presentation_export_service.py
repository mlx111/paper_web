import zipfile
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class PresentationExportServiceTest(unittest.TestCase):
    def test_export_uses_layout_design_and_embeds_images(self):
        from services.presentation_export_service import PresentationExportService

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            image_path = root / "figure.png"
            image_path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
                b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04"
                b"\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            output_path = root / "output.pptx"

            plan = {
                "title": "Enterprise RAG overview",
                "audience": "AI engineering interns",
                "design": {
                    "theme": {
                        "palette": {
                            "background": "#F8FAFC",
                            "surface": "#FFFFFF",
                            "primary": "#1D4ED8",
                            "secondary": "#0F766E",
                            "accent": "#D97706",
                            "text": "#0F172A",
                            "muted": "#64748B",
                        }
                    }
                },
                "slides": [
                    {
                        "title": "Cover",
                        "layout": "cover",
                        "bullets": ["Enterprise RAG overview"],
                        "elements": [{"type": "title", "text": "Enterprise RAG overview"}],
                        "design": {"role": "hero", "accent": "primary"},
                    },
                    {
                        "title": "Evidence",
                        "layout": "image_text",
                        "bullets": ["Relevant architecture diagram"],
                        "elements": [
                            {"type": "title", "text": "Evidence"},
                            {"type": "bullet", "text": "Relevant architecture diagram"},
                            {"type": "image", "text": str(image_path)},
                            {"type": "caption", "text": "Architecture figure"},
                        ],
                        "design": {"role": "visual", "accent": "secondary"},
                    },
                ],
            }

            PresentationExportService().export(plan=plan, manuscript="", output_path=output_path)

            with zipfile.ZipFile(output_path) as archive:
                names = archive.namelist()
                slide_xml = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in names
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )

            self.assertTrue(any(name.startswith("ppt/media/") for name in names))
            self.assertIn("1D4ED8", slide_xml)
            self.assertIn("0F766E", slide_xml)
            self.assertIn("Architecture figure", slide_xml)


if __name__ == "__main__":
    unittest.main()
