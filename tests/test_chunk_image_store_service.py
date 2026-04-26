import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class ChunkImageStoreServiceTest(unittest.TestCase):
    def test_save_image_persists_mapping_and_resolves_public_url(self):
        from services.chunk_image_store_service import ChunkImageStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ChunkImageStore(
                image_root=root / "images",
                mapping_path=root / "chunk_images.json",
                public_url_prefix="/file/image",
            )

            record = store.save_image(
                image_bytes=b"fake-image",
                ext="png",
                file_id="paper-1",
                file_name="paper.pdf",
                chunk_id="chunk-1",
                page_number=2,
                sort_order=0,
            )

            self.assertRegex(record["placeholder"], r"^<<IMAGE:[0-9a-f]{8}>>$")
            self.assertTrue(Path(record["image_path"]).exists())

            reloaded = ChunkImageStore(root / "images", root / "chunk_images.json", "/file/image")
            image_map = reloaded.resolve_image_map([record["placeholder"]])

            self.assertEqual(
                image_map,
                {record["placeholder"]: f"/file/image/{record['image_id']}"},
            )

    def test_extract_placeholders_keeps_order_without_duplicates(self):
        from services.chunk_image_store_service import (
            extract_image_placeholders,
            strip_image_placeholders,
        )

        text = "A <<IMAGE:1111aaaa>> B <<IMAGE:2222bbbb>> C <<IMAGE:1111aaaa>>"

        self.assertEqual(
            extract_image_placeholders(text),
            ["<<IMAGE:1111aaaa>>", "<<IMAGE:2222bbbb>>"],
        )
        self.assertEqual(strip_image_placeholders(text), "A B C")

    def test_resolve_image_map_from_text(self):
        from services.chunk_image_store_service import ChunkImageStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ChunkImageStore(root / "images", root / "chunk_images.json", "/file/image")
            record = store.save_image(
                image_bytes=b"fake-image",
                ext="png",
                file_id="paper-1",
                file_name="paper.pdf",
                chunk_id="chunk-1",
            )

            text = f"参考图如下 {record['placeholder']}"

            self.assertEqual(
                store.resolve_image_map_from_text(text),
                {record["placeholder"]: f"/file/image/{record['image_id']}"},
            )


if __name__ == "__main__":
    unittest.main()
