import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

for name in ["loguru"]:
    sys.modules.setdefault(name, types.ModuleType(name))

sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)


class HealthServiceTest(unittest.TestCase):
    def test_build_health_report_marks_core_services_ok(self):
        from services.health_service import build_health_report

        report = build_health_report(
            app_name="MyPaperWeb",
            app_version="1.0.0",
            debug=True,
            model_key="real-key",
            milvus_checker=lambda: True,
            redis_url="",
            db_url="",
        )

        self.assertEqual(report["status"], "warn")
        self.assertEqual(report["services"]["api"]["status"], "ok")
        self.assertEqual(report["services"]["model_key"]["status"], "ok")
        self.assertEqual(report["services"]["milvus"]["status"], "ok")
        self.assertEqual(report["services"]["redis"]["status"], "warn")
        self.assertEqual(report["services"]["database"]["status"], "warn")

    def test_build_health_report_marks_failed_required_service_unhealthy(self):
        from services.health_service import build_health_report

        report = build_health_report(
            app_name="MyPaperWeb",
            app_version="1.0.0",
            debug=True,
            model_key="your_dashscope_api_key",
            milvus_checker=lambda: False,
            redis_url="",
            db_url="",
        )

        self.assertEqual(report["status"], "error")
        self.assertEqual(report["services"]["model_key"]["status"], "error")
        self.assertEqual(report["services"]["milvus"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
