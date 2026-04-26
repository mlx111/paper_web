import asyncio
import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


fastapi_module = types.ModuleType("fastapi")
fastapi_module.HTTPException = HTTPException
sys.modules["fastapi"] = fastapi_module

core_module = types.ModuleType("core")
redis_module = types.ModuleType("core.redis")
redis_module.redis_client = None
sys.modules.setdefault("core", core_module)
sys.modules["core.redis"] = redis_module

from utils import code as code_utils


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.deleted = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)

    async def incr(self, key):
        next_value = int(self.values.get(key, 0)) + 1
        self.values[key] = next_value
        return next_value

    async def expire(self, key, seconds):
        return True


class VerificationCodeTest(unittest.TestCase):
    def test_expired_code_raises_http_exception(self):
        fake_redis = FakeRedis()
        code_utils.redis_client = fake_redis

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(code_utils.verify_code("user@example.com", "123456"))

        self.assertEqual(exc.exception.status_code, 400)

    def test_valid_code_is_verified_and_deleted_by_email(self):
        fake_redis = FakeRedis()
        fake_redis.values["mail_code:user@example.com"] = "123456"
        fake_redis.values["fail_count:user@example.com"] = 2
        code_utils.redis_client = fake_redis

        result = asyncio.run(code_utils.verify_code("user@example.com", "123456"))

        self.assertTrue(result)
        self.assertIn("mail_code:user@example.com", fake_redis.deleted)
        self.assertIn("fail_count:user@example.com", fake_redis.deleted)


if __name__ == "__main__":
    unittest.main()
