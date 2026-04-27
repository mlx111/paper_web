import builtins
import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class MailCompatTest(unittest.TestCase):
    def test_patch_fastapi_mail_compat_sets_builtin_secretstr(self):
        from core.mail import _patch_fastapi_mail_compat

        original = getattr(builtins, "SecretStr", None)
        if hasattr(builtins, "SecretStr"):
            delattr(builtins, "SecretStr")

        fake_pydantic = types.ModuleType("pydantic")

        class FakeSecretStr:
            pass

        fake_pydantic.SecretStr = FakeSecretStr
        original_pydantic = sys.modules.get("pydantic")
        sys.modules["pydantic"] = fake_pydantic
        try:
            _patch_fastapi_mail_compat()
            self.assertIs(getattr(builtins, "SecretStr"), FakeSecretStr)
        finally:
            if original is None:
                if hasattr(builtins, "SecretStr"):
                    delattr(builtins, "SecretStr")
            else:
                builtins.SecretStr = original

            if original_pydantic is None:
                sys.modules.pop("pydantic", None)
            else:
                sys.modules["pydantic"] = original_pydantic


if __name__ == "__main__":
    unittest.main()
