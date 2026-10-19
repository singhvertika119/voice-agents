"""Fetch a public web page without letting a user-supplied URL reach our own network (SSRF protection)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from .parsers import ParseError

MAX_BYTES = 5_000_000


def assert_public(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ParseError("Enter a full web address starting with http:// or https://")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ParseError("That web address could not be found. Check the spelling.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ParseError("That address is not a public website, so it cannot be read.")


async def fetch_public_html(url: str, max_redirects: int = 3) -> str:
    headers = {"User-Agent": "VoiceAgentsBot/0.1 (+knowledge import)", "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers=headers) as c:
        for _ in range(max_redirects + 1):
            assert_public(url)  # re-check every hop: a redirect can point inside our network
            async with c.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                if r.status_code >= 400:
                    raise ParseError(f"The website answered with an error ({r.status_code}). Check the address or paste the text instead.")
                if "html" not in r.headers.get("content-type", "html"):
                    raise ParseError("That address is not a web page. For files, use Upload.")
                body = b""
                async for part in r.aiter_bytes():
                    body += part
                    if len(body) > MAX_BYTES:
                        raise ParseError("That page is too large to import.")
                return body.decode(r.encoding or "utf-8", errors="replace")
    raise ParseError("That address redirects too many times.")
