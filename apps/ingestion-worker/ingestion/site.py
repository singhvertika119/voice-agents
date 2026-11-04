"""Read a whole website, not one page, and keep everything a visitor can read on it (D-110).

Before this a website source was one page passed through trafilatura, a news-article extractor. On business sites
that lost what callers ask about most: nialabs.in kept 40% of its home page's visible text, and its contact page lost
the address, phone, hours and email entirely; every other page of the site (contact, products, FAQ) was never read.

Now: the pages of the site are found (its sitemap first, then its links), fetched with the same public-address checks
as before, and each page's visible text is kept in reading order. Menus and footers that repeat on every page are
kept once, in a section of their own, instead of on every page or not at all.
"""
from __future__ import annotations

import asyncio
import os
import re
from collections import Counter
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from .netsafe import fetch_public_page
from .parsers import ParseError, Parsed

MAX_PAGES = int(os.getenv("WEBSITE_MAX_PAGES", "40"))
MAX_BLOG_PAGES = 5            # a blog can have hundreds of posts; a few are enough, the rest crowd out the real pages
MIN_NEW_LINES = 5             # a page adding fewer new lines than this is a copy (a tracking variant, a print view)
MAX_SITE_CHARS = 240_000      # stop reading once this much text is kept (about 800 sections, under the 1,000 limit)
FETCH_BUDGET = 2              # fetch up to this many times MAX_PAGES while looking for pages that add something
FETCH_PARALLEL = 4
AGENT = "VoiceAgentsBot"

# Pages a caller never needs: sign-in, shopping steps, legal text, feeds and plumbing.
SKIP = re.compile(r"(login|log-in|signin|sign-in|signup|register|logout|admin|wp-admin|wp-json|cart|checkout|account|"
                  r"privacy|terms|cookie|refund-policy|cdn-cgi|/feed|/tag/|/author/|/page/\d|xmlrpc)", re.I)
FILES = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|mp4|mp3|docx?|xlsx?|pptx?|css|js|json|xml|txt|ico)$", re.I)
# What callers ask about most: these pages are read first, whatever the menu order.
PRIORITY = re.compile(r"(?:^|[/-])(contact|about|faqs?|pricing|prices?|fees|locations?|timings?|hours|branch(?:es)?|"
                      r"offices?|reach-us|support)(?:$|[/-])", re.I)
BLOG = re.compile(r"/(blog|blogs|news|articles|insights|stories|category)(/|$)", re.I)

DROP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "form", "button", "select", "option",
             "input", "textarea", "canvas", "video", "audio", "picture", "img", "head"}
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dt", "dd", "address", "blockquote",
              "figcaption", "summary", "caption", "pre"}
HEADINGS = {"h1": "##", "h2": "###", "h3": "####", "h4": "####"}
CHROME_TAGS = {"header", "footer", "nav", "aside"}            # the site's frame around the page's own content
CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
STRUCTURE_TAGS = BLOCK_TAGS | {"div", "section", "article", "main", "header", "footer", "nav", "aside", "ul", "ol",
                               "table", "tr", "details", "dl"}


# ------------------------------------------------------------------ finding pages
def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _clean(url: str) -> str:
    url = urldefrag(url)[0].split("?")[0]
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}"


def _wanted(url: str, host: str, prefix: str) -> bool:
    p = urlparse(url)
    return (p.scheme in ("http", "https") and _host(url) == host and p.path.rstrip("/").startswith(prefix)
            and not SKIP.search(p.path) and not FILES.search(p.path))


def _links(html: str, base: str) -> list[str]:
    return [urljoin(base, h) for h in re.findall(r"""<a\s[^>]*?href\s*=\s*["']([^"'#][^"']*)["']""", html, re.I)]


async def _text(url: str) -> str | None:
    try:
        return (await fetch_public_page(url, html_only=False))[1]
    except Exception:
        return None


async def _sitemap_urls(root: str, robots_txt: str | None) -> list[str]:
    """Addresses listed in the site's sitemap(s): robots.txt names them, /sitemap.xml is the usual place."""
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt or "") or [urljoin(root, "/sitemap.xml")]
    found: list[str] = []
    for m in maps[:3]:
        xml = await _text(m)
        if not xml or "<loc" not in xml:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
        if "<sitemapindex" in xml:   # an index of sitemaps: read the first few
            for child in locs[:5]:
                sub = await _text(child)
                found += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sub or "")
        else:
            found += locs
    return found


def _order(urls: list[str], start: str, first_links: list[str]) -> list[str]:
    """Pages the home page links to come first, in its order (its menu is the owner's own list of what matters);
    then the rest of the site, shallow pages before deep ones, blog posts last."""
    linked = {u: i for i, u in enumerate(dict.fromkeys(first_links))}
    def key(u: str) -> tuple:
        path = urlparse(u).path
        key_page = bool(PRIORITY.search(path)) and not BLOG.search(path)
        return (u != start, not key_page, u not in linked, linked.get(u, 0), bool(BLOG.search(path)),
                path.count("/"), len(path))
    return sorted(dict.fromkeys(urls), key=key)


async def crawl(start_url: str, max_pages: int = MAX_PAGES) -> list[tuple[str, str]]:
    """[(address, html)] for up to max_pages pages of the site, the start page first.

    Entering the home page reads the whole site; entering a deeper page ("/fees") reads that page and the pages under
    it. Only the same site is followed (www. or not), robots.txt is respected, and a page that fails is skipped.
    Contact, about, FAQ and pricing pages come first, then the pages the home page links to, so the limit leaves out
    the least important pages (on nialabs.in, ordering by depth alone spent 12 of 40 places on "... in Pune",
    "... in Delhi" pages and never reached the product pages). Copies that add almost nothing are skipped."""
    final, first = await fetch_public_page(start_url)   # an error here is the owner's to see, as before
    start = _clean(final)
    host = _host(start)
    prefix = urlparse(start).path.rstrip("/")
    root = f"{urlparse(start).scheme}://{urlparse(start).netloc}"

    robots_txt = await _text(urljoin(root, "/robots.txt"))
    robots = RobotFileParser()
    robots.parse((robots_txt or "").splitlines())
    allowed = lambda u: robots_txt is None or robots.can_fetch(AGENT, u)  # noqa: E731
    ok = lambda u: _wanted(u, host, prefix) and allowed(u)  # noqa: E731

    first_links = [u for u in (_clean(x) for x in _links(first, final)) if ok(u)]
    sitemap = [u for u in (_clean(x) for x in await _sitemap_urls(root, robots_txt)) if ok(u)]
    queue = [u for u in _order(first_links + sitemap, start, first_links) if u != start]

    pages: dict[str, str] = {start: first}
    known: set[str] = {ln.lower() for ln in page_lines(first)[1]}
    size = sum(len(ln) for ln in known)
    tried: set[str] = {start}
    blog = 0
    sem = asyncio.Semaphore(FETCH_PARALLEL)

    async def get(u: str) -> tuple[str, str] | None:
        async with sem:
            try:
                f, html = await fetch_public_page(u)
                return _clean(f), html
            except Exception:
                return None

    for step in range(2):   # the listed pages, then one more step of links if the site has room left
        while queue and len(pages) < max_pages and len(tried) < max_pages * FETCH_BUDGET and size < MAX_SITE_CHARS:
            batch = []
            while queue and len(batch) < FETCH_PARALLEL * 2:
                u = queue.pop(0)
                if u in tried:
                    continue
                if BLOG.search(urlparse(u).path):
                    if blog >= MAX_BLOG_PAGES:
                        continue
                    blog += 1
                tried.add(u)
                batch.append(u)
            for got in await asyncio.gather(*(get(u) for u in batch)):
                if not got or _host(got[0]) != host or got[0] in pages or len(pages) >= max_pages or size >= MAX_SITE_CHARS:
                    continue
                new = {ln.lower() for ln in page_lines(got[1])[1]} - known
                if len(new) >= MIN_NEW_LINES:
                    pages[got[0]] = got[1]
                    known |= new
                    size += sum(len(ln) for ln in new)
        if step == 1 or len(pages) >= max_pages or size >= MAX_SITE_CHARS:
            break
        more = [_clean(u) for page_url, html in list(pages.items()) for u in _links(html, page_url)]
        queue = [u for u in _order([u for u in more if ok(u)], start, first_links) if u not in tried]
    return list(pages.items())


# ------------------------------------------------------------------ reading pages
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _hidden(el) -> bool:
    style = (el.get("style") or "").replace(" ", "").lower()
    return el.get("hidden") is not None or el.get("aria-hidden") == "true" or "display:none" in style


def page_lines(html: str) -> tuple[str, list[str]]:
    """(page title, lines of visible text in reading order). Headings come out as markdown headings."""
    title, lines = page_parts(html)
    return title, [ln for ln, _ in lines]


def page_parts(html: str) -> tuple[str, list[tuple[str, bool]]]:
    """(page title, [(line, is_frame)]): is_frame marks text inside the site's header, menu or footer."""
    import lxml.html

    try:
        tree = lxml.html.fromstring(html)
    except Exception:
        return "", []
    title = _norm((tree.findtext(".//title") or "").split("|")[0].split(" - ")[0]) or ""
    out: list[tuple[str, bool]] = []

    def emit(text: str, frame: bool, tag: str = "") -> None:
        t = _norm(text)
        if len(t) < 2:
            return
        out.append((f"{HEADINGS[tag]} {t}" if tag in HEADINGS else t, frame))

    def walk(el, frame: bool) -> None:
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in DROP_TAGS or not tag or _hidden(el):
            return
        frame = frame or tag in CHROME_TAGS or (el.get("role") or "") in CHROME_ROLES
        if tag in BLOCK_TAGS or not any(isinstance(d.tag, str) and d.tag in STRUCTURE_TAGS for d in el.iterdescendants()):
            emit(el.text_content(), frame, tag)   # a block, or a box with no blocks inside: its text is one line
            return
        emit(el.text or "", frame)
        for child in el:
            walk(child, frame)
            emit(child.tail or "", frame)

    body = tree.find(".//body")
    walk(body if body is not None else tree, False)
    return title, out


def _keep(line: str) -> bool:
    """Drop lone menu words ("Products", "Login") but keep anything with a digit or an @ (phones, prices, email)."""
    return line.startswith("#") or len(line.split()) >= 2 or bool(re.search(r"[\d@]", line))


def extract_site(pages: list[tuple[str | None, str]]) -> Parsed:
    """Markdown for the whole site: one section per page with all of that page's own content, then the site's frame
    (menus, footer: the same on every page) once. A page keeps its own content even when the frame repeats it, so
    the contact page keeps the address the footer also shows (dropping it there left "Our Location" empty)."""
    read = [(url, *page_parts(html)) for url, html in pages]
    seen_on = Counter()
    for _, _, lines in read:
        seen_on.update({ln.lower() for ln, frame in lines if not frame})   # frame text is counted separately
    n = len(read)
    # Text on 3 or more pages is a site element (a menu without header/footer tags, a "related products" strip that
    # every product page repeats) and is kept once with the frame: on nialabs.in such a strip filled the top results
    # for "NiaFace A100 features" and pushed out the A100 page itself (D-110).
    everywhere = {ln for ln, c in seen_on.items() if n >= 3 and c >= 3 and not ln.startswith("#")}

    parts: list[str] = []
    shared: list[str] = []
    shared_keys: set[str] = set()
    for url, title, lines in read:
        mine, done = [], set()
        for ln, frame in lines:
            key = ln.lower()
            if not _keep(ln):
                continue
            if frame or (key in everywhere and not re.search(r"[\d@]", ln)):   # a phone or email stays on its page too
                if key not in shared_keys and not ln.startswith("#"):
                    shared_keys.add(key)
                    shared.append(ln)
                continue
            if key in done and not re.search(r"[\d@]", ln):   # a number or email is kept where it appears again:
                continue                                      # "Phone Number" lost its number when it was dropped
            done.add(key)
            mine.append(ln)
        if mine:
            name = title or (urlparse(url).path if url else "") or "Page"
            where = f" ({urlparse(url).path})" if url and urlparse(url).path not in ("", "/") else ""
            parts.append(f"# {name}{where}\n" + "\n".join(mine))
    if shared:   # right after the home page: if a very large site is cut to the section limit, this is not the part lost
        parts.insert(min(1, len(parts)), "# On every page of the website\n" + "\n".join(shared))
    md = "\n\n".join(parts).strip()
    if len(md) < 80:
        raise ParseError("Not enough readable text was found on this website. It may need JavaScript to load, or may be blocked. Paste the text instead.")
    return Parsed(markdown=md, pages=[u for u, _ in pages if u])
