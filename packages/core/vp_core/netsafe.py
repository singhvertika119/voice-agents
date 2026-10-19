"""Refuse web addresses that point into our own network (SSRF protection), for customer-supplied URLs."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    pass


def assert_public_url(url: str, https_only: bool = False) -> None:
    p = urlparse(url)
    allowed = ("https",) if https_only else ("http", "https")
    if p.scheme not in allowed or not p.hostname:
        raise UnsafeURL("Enter a full web address starting with " + ("https://" if https_only else "http:// or https://"))
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURL("That web address could not be found. Check the spelling.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise UnsafeURL("That address is not a public website, so it cannot be used.")
