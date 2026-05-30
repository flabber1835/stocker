import sys
import os
import types
from unittest.mock import AsyncMock, MagicMock

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Stub `redis` and `redis.asyncio` so importing pipeline.app.main does not
# require the redis library at test time.
if "redis" not in sys.modules:
    _redis = types.ModuleType("redis")
    _redis_async = types.ModuleType("redis.asyncio")

    class _FakeRedis:
        @classmethod
        def from_url(cls, *a, **k):
            inst = MagicMock()
            inst.xgroup_create = AsyncMock()
            inst.xreadgroup = AsyncMock(return_value=[])
            inst.xack = AsyncMock()
            inst.aclose = AsyncMock()
            return inst

    # redis.exceptions.TimeoutError — app.main imports it to treat an idle-stream
    # blocking-read timeout as benign (not an error). Stub it so import succeeds.
    _redis_exceptions = types.ModuleType("redis.exceptions")

    class _FakeRedisTimeoutError(Exception):
        pass

    _redis_exceptions.TimeoutError = _FakeRedisTimeoutError

    _redis_async.Redis = _FakeRedis
    _redis_async.from_url = _FakeRedis.from_url
    _redis.asyncio = _redis_async
    _redis.exceptions = _redis_exceptions
    sys.modules["redis"] = _redis
    sys.modules["redis.asyncio"] = _redis_async
    sys.modules["redis.exceptions"] = _redis_exceptions

# Default DATABASE_URL so importing app.main doesn't fail on missing env.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@x/x")
os.environ.setdefault("STRATEGY_CONFIG_PATH",
                      os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))

for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "pipeline"))
