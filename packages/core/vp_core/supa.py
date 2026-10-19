"""Minimal async Supabase client (PostgREST + Storage) using the service-role key.

The service role bypasses row-level security, so callers must always scope queries by tenant_id themselves.
"""
from __future__ import annotations

import os

import httpx


def _env() -> tuple[str, str]:
    return os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def client(timeout: float = 20) -> httpx.AsyncClient:
    url, key = _env()
    return httpx.AsyncClient(
        base_url=url, timeout=timeout,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=representation"},
    )


async def select(table: str, **params) -> list[dict]:
    async with client() as c:
        r = await c.get(f"/rest/v1/{table}", params=params)
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


async def rpc(fn: str, args: dict, timeout: float = 20) -> list[dict]:
    async with client(timeout) as c:
        r = await c.post(f"/rest/v1/rpc/{fn}", json=args)
        r.raise_for_status()
        return r.json()


async def download(bucket: str, path: str) -> bytes:
    async with client(60) as c:
        r = await c.get(f"/storage/v1/object/{bucket}/{path}")
        if r.status_code == 404:
            raise FileNotFoundError(path)
        r.raise_for_status()
        return r.content
