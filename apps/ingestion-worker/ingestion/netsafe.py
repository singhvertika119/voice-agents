"""Fetch a public web page without letting a user-supplied URL reach our own network (SSRF protection)."""
from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import httpx
from vp_core.netsafe import UnsafeURL, assert_public_url

from .parsers import ParseError

MAX_BYTES = 5_000_000


def assert_public(url: str) -> None:
    """The shared check (vp_core.netsafe), raising the ingestion worker's own error type so it reaches the dashboard."""
    try:
        assert_public_url(url)
    except UnsafeURL as e:
        raise ParseError(str(e)) from e


async def fetch_public_page(url: str, max_redirects: int = 3, html_only: bool = True) -> tuple[str, str]:
    """(final address after redirects, body). Every hop is checked to be a public address. html_only=False also
    accepts plain text and XML (robots.txt and sitemaps, D-110)."""
    headers = {"User-Agent": "VoiceAgentsBot/0.1 (+knowledge import)",
               "Accept": "text/html,application/xhtml+xml" if html_only else "text/html,text/plain,application/xml,text/xml,*/*"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers=headers) as c:
        for _ in range(max_redirects + 1):
            await asyncio.to_thread(assert_public, url)  # re-check every hop; the DNS lookup blocks, so it runs in a thread
            async with c.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                if r.status_code >= 400:
                    raise ParseError(f"The website answered with an error ({r.status_code}). Check the address or paste the text instead.")
                if html_only and "html" not in r.headers.get("content-type", "html"):
                    raise ParseError("That address is not a web page. For files, use Upload.")
                body = b""
                async for part in r.aiter_bytes():
                    body += part
                    if len(body) > MAX_BYTES:
                        raise ParseError("That page is too large to import.")
                return url, body.decode(r.encoding or "utf-8", errors="replace")
    raise ParseError("That address redirects too many times.")
