"""Minimal async Supabase client (PostgREST + Storage) using the service-role key.

The service role bypasses row-level security, so callers must always scope queries by tenant_id themselves.
"""
from __future__ import annotations

import asyncio
import os
import time

import httpx

_pool: dict = {}   # one open connection pool per event loop (D-110)


def _env() -> tuple[str, str]:
    return os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def client(timeout: float = 20) -> httpx.AsyncClient:
    url, key = _env()
    return httpx.AsyncClient(
        base_url=url, timeout=timeout,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=representation"},
    )


def pooled() -> httpx.AsyncClient:
    """A client that stays open and is reused, so a request does not pay for a new connection. The database is in
    Seoul and a new secure connection costs several round trips: a plain lookup took 0.6 to 0.7 s that way, which is
    most of the 2 s a call allows for a knowledge search. Kept per event loop, because a client cannot move between
    loops (scripts and tests start a new loop each time)."""
    loop = asyncio.get_running_loop()
    entry = _pool.get("c")
    if entry is None or entry[0] is not loop or entry[1].is_closed:
        url, key = _env()
        c = httpx.AsyncClient(base_url=url, timeout=20, limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=60),
                              headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=representation"})
        _pool["c"] = (loop, c)
    return _pool["c"][1]


async def select(table: str, **params) -> list[dict]:
    r = await pooled().get(f"/rest/v1/{table}", params=params)
    r.raise_for_status()
    return r.json()


async def insert(table: str, rows: list[dict] | dict) -> list[dict]:
    async with client(60) as c:
        r = await c.post(f"/rest/v1/{table}", json=rows)
        r.raise_for_status()
        return r.json()


async def update(table: str, match: dict, values: dict) -> list[dict]:
    async with client() as c:
        r = await c.patch(f"/rest/v1/{table}", params={k: f"eq.{v}" for k, v in match.items()}, json=values)
        r.raise_for_status()
        return r.json()


async def delete(table: str, match: dict) -> None:
    async with client() as c:
        r = await c.delete(f"/rest/v1/{table}", params={k: f"eq.{v}" for k, v in match.items()})
        r.raise_for_status()


async def rpc(fn: str, args: dict, timeout: float = 20, trace: dict | None = None) -> list[dict]:
    """trace: if given, filled with how the request went (D-120): new_connection, and ms for connecting, the secure
    handshake, and waiting for the answer, plus which pooled client was used."""
    ext = {}
    if trace is not None:
        t0 = time.perf_counter()
        marks: dict[str, float] = {}

        async def on(name: str, info: dict) -> None:
            marks[name] = time.perf_counter()

        ext = {"trace": on}
    c = pooled()
    r = await c.post(f"/rest/v1/rpc/{fn}", json=args, timeout=timeout, extensions=ext)
    if trace is not None:
        ms = lambda a, b: round((marks[b] - marks[a]) * 1000) if a in marks and b in marks else None  # noqa: E731
        trace.update({
            "new_connection": "connection.connect_tcp.started" in marks,
            "connect_ms": ms("connection.connect_tcp.started", "connection.connect_tcp.complete"),
            "tls_ms": ms("connection.start_tls.started", "connection.start_tls.complete"),
            "answer_ms": next((v for v in (ms("http11.send_request_headers.started", "http11.receive_response_headers.complete"),
                                           ms("http2.send_request_headers.started", "http2.receive_response_headers.complete"))
                               if v is not None), None),
            "total_ms": round((time.perf_counter() - t0) * 1000),
            "client": id(c) % 10000,
            "http": r.http_version,
        })
    r.raise_for_status()
    return r.json()


async def download(bucket: str, path: str) -> bytes:
    async with client(60) as c:
        r = await c.get(f"/storage/v1/object/{bucket}/{path}")
        if r.status_code == 404:
            raise FileNotFoundError(path)
        r.raise_for_status()
        return r.content


async def upload(bucket: str, path: str, data: bytes, content_type: str) -> None:
    """Create or replace one object. Service key only: callers must have checked the workspace themselves."""
    async with client(120) as c:
        r = await c.post(f"/storage/v1/object/{bucket}/{path}", content=data,
                         headers={"Content-Type": content_type, "x-upsert": "true"})
        r.raise_for_status()


async def remove(bucket: str, paths: list[str]) -> None:
    if not paths:
        return
    async with client(60) as c:
        r = await c.request("DELETE", f"/storage/v1/object/{bucket}", json={"prefixes": paths})
        r.raise_for_status()
