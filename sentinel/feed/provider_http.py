"""Cancellable HTTP observations behind the synchronous acquisition boundary."""
import asyncio
from contextlib import contextmanager
from urllib.error import HTTPError

from anyio.from_thread import start_blocking_portal
import httpx

from sentinel.feed import provider_budget


async def _fetch(client, request, limit):
    left = provider_budget.remaining()
    if left is not None and left <= 0:
        raise TimeoutError("source acquisition deadline expired")
    headers = dict(request.header_items())
    headers['Accept-Encoding'] = 'identity'
    async with asyncio.timeout(left):
        async with client.stream(request.get_method(), request.full_url, headers=headers,
                                 content=request.data, timeout=min(left, 45) if left is not None else 45) as response:
            if response.status_code != 200:
                raise HTTPError(request.full_url, response.status_code, response.reason_phrase, response.headers, None)
            raw = bytearray()
            async for chunk in response.aiter_raw():
                raw.extend(chunk[:limit + 1 - len(raw)])
                if len(raw) > limit:
                    break
            return raw


@contextmanager
def pool():
    with start_blocking_portal() as portal:
        client = httpx.AsyncClient(follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2))
        try:
            yield lambda request, limit: portal.call(_fetch, client, request, limit)
        finally:
            portal.call(client.aclose)


def fetch(request, limit):
    with pool() as read:
        return read(request, limit)
