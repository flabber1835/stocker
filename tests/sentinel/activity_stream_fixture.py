"""HTTPX streaming interface for synthetic finite broker routes."""
from contextlib import asynccontextmanager

import httpx


class ActivityStreamClient:
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        assert method == "GET"
        assert kwargs.pop("timeout") == 60.0
        response = await self.get(url, **kwargs)

        async def chunks():
            payload = response.text.encode("utf-8")
            for start in range(0, len(payload), 97):
                yield payload[start:start + 97]

        streamed = httpx.Response(response.status_code, content=chunks(),
                                  request=httpx.Request(method, url))
        try:
            yield streamed
        finally:
            await streamed.aclose()
