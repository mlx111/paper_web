import tempfile
import time
import unittest
from pathlib import Path


class TempFileServiceTest(unittest.TestCase):
    def test_save_temp_file_enforces_count_limit_and_lists_files(self):
        from app.services.temp_file_service import TempFileService

        with tempfile.TemporaryDirectory() as temp_dir:
            service = TempFileService(
                root_dir=Path(temp_dir),
                max_files_per_session=2,
                max_file_size_bytes=1024,
                max_total_size_bytes=2048,
                ttl_seconds=3600,
            )

            first = service.save_temp_file("session-a", "one.txt", b"one")
            second = service.save_temp_file("session-a", "two.md", b"two")
            third = service.save_temp_file("session-a", "three.txt", b"three")

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertFalse(third["ok"])
            self.assertEqual(third["error"], "TEMP_FILE_LIMIT_EXCEEDED")

            files = service.list_temp_files("session-a")
            self.assertEqual(len(files), 2)
            self.assertEqual([item["filename"] for item in files], ["one.txt", "two.md"])

    def test_save_temp_file_rejects_large_file(self):
        from app.services.temp_file_service import TempFileService

        with tempfile.TemporaryDirectory() as temp_dir:
            service = TempFileService(
                root_dir=Path(temp_dir),
                max_files_per_session=5,
                max_file_size_bytes=4,
                max_total_size_bytes=1024,
                ttl_seconds=3600,
            )

            result = service.save_temp_file("session-a", "large.txt", b"12345")

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "TEMP_FILE_TOO_LARGE")

    def test_cleanup_expired_files_removes_old_session_files(self):
        from app.services.temp_file_service import TempFileService

        with tempfile.TemporaryDirectory() as temp_dir:
            service = TempFileService(
                root_dir=Path(temp_dir),
                max_files_per_session=5,
                max_file_size_bytes=1024,
                max_total_size_bytes=2048,
                ttl_seconds=1,
            )
            result = service.save_temp_file("session-a", "old.txt", b"old")
            path = Path(result["file_path"])
            old_time = time.time() - 10
            path.touch()
            path.stat()
            import os

            os.utime(path, (old_time, old_time))

            removed = service.cleanup_expired_files()

            self.assertEqual(removed, 1)
            self.assertEqual(service.list_temp_files("session-a"), [])


if __name__ == "__main__":
    unittest.main()
