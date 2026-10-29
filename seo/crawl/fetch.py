"""Fetching pages politely and discovering URLs from the sitemap."""
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from ..config import settings

UA = "LabEffectsSEOMonitor/1.0 (+https://labeffects.com; internal site health check)"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})

# Shopify URL patterns we do not crawl as pages (they are not SEO surfaces)
SKIP_PATTERNS = re.compile(
    r"(/cart|/account|/checkouts?|/search|/cdn/|/apps/|/policies/|\.(png|jpe?g|gif|webp|avif|svg|pdf|css|js|ico|xml|json)$|[?&](variant|page|sort_by|filter)=|/collections/[^/]+/products/)",
    re.I,
)


@dataclass
class Fetched:
    url: str
    status: int
    final_url: str
    redirect_hops: int
    html: str
    content_type: str
    elapsed_ms: int
    error: str = ""
    history: list = field(default_factory=list)


def normalize(url: str, base: str = "") -> str:
    """Resolve relative URLs, drop fragments, strip trailing slash except root."""
    if base:
        url = urljoin(base, url)
    p = urlparse(url)
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def is_internal(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == settings.host or host == "www." + settings.host


def should_crawl(url: str) -> bool:
    return is_internal(url) and not SKIP_PATTERNS.search(url)


def fetch(url: str, timeout: int = 20) -> Fetched:
    t0 = time.time()
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        ms = int((time.time() - t0) * 1000)
        ct = r.headers.get("Content-Type", "")
        html = r.text if "html" in ct or "xml" in ct else ""
        return Fetched(url=url, status=r.status_code, final_url=normalize(r.url), redirect_hops=len(r.history),
                       html=html, content_type=ct, elapsed_ms=ms, history=[h.url for h in r.history])
    except requests.RequestException as e:
        ms = int((time.time() - t0) * 1000)
        return Fetched(url=url, status=0, final_url=url, redirect_hops=0, html="", content_type="", elapsed_ms=ms, error=str(e)[:200])


def head_status(url: str, timeout: int = 15) -> tuple[int, int, str]:
    """Cheap status check for link targets: (status, redirect_hops, final_url)."""
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code in (405, 403):  # some hosts refuse HEAD
            r = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
            r.close()
        return r.status_code, len(r.history), normalize(r.url)
    except requests.RequestException:
        return 0, 0, url


def sitemap_urls(site_url: str) -> list[str]:
    """Read sitemap.xml (and any nested sitemaps) and return page URLs."""
    found: list[str] = []
    seen: set[str] = set()
    queue = [site_url.rstrip("/") + "/sitemap.xml"]
    while queue:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        f = fetch(sm)
        if f.status != 200 or not f.html:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", f.html)
        if "<sitemapindex" in f.html:
            queue.extend(locs)
        else:
            found.extend(locs)
    out, dedupe = [], set()
    for u in found:
        n = normalize(u)
        if n not in dedupe and should_crawl(n):
            dedupe.add(n)
            out.append(n)
    return out


def polite_sleep():
    if settings.crawl_delay_seconds > 0:
        time.sleep(settings.crawl_delay_seconds)
