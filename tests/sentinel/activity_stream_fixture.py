"""HTTPX streaming interface for synthetic finite broker routes."""
from contextlib import asynccontextmanager


class ActivityStreamClient:
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        assert method == "GET"
        assert kwargs.pop("timeout") == 60.0
        response = await self.get(url, **kwargs)

        async def lines():
            for line in response.text.splitlines():
                yield line

        response.aiter_lines = lines
        yield response
