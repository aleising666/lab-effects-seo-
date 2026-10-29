"""Turn a fetched HTML page into the facts the checks need."""
import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .fetch import normalize, is_internal

# Shopify theme specifics for labeffects.com. Kept in one place so a theme
# change only touches this file.
BRAND_SUFFIX = " – Lab Effects Shop"          # the theme appends this to every <title>
MAIN_SELECTORS = [".ar-prose", "#lab-col-region", "main", "body"]
FAQ_QUESTION_SELECTOR = ".lab-col-faqitem__q, [data-faq-q]"
KNOWN_SHORTCODES = re.compile(r"^\[(product|cta|takeaways|figure|faq)\b", re.I)


@dataclass
class Page:
    url: str
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    robots: str = ""
    h1s: list = field(default_factory=list)
    h2s: list = field(default_factory=list)
    word_count: int = 0
    body_text: str = ""
    internal_links: list = field(default_factory=list)   # (href, anchor_text)
    external_links: list = field(default_factory=list)
    images: list = field(default_factory=list)           # (src, alt)
    faq_visible: list = field(default_factory=list)
    faq_schema: list = field(default_factory=list)
    schema_types: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)
    page_type: str = "other"


def page_type_of(url: str) -> str:
    p = url.split("//", 1)[-1].split("/", 1)[1] if "/" in url.split("//", 1)[-1] else ""
    if p.startswith("blogs/") and p.count("/") >= 2:
        return "article"
    if p.startswith("blogs/"):
        return "blog"
    if p.startswith("products/"):
        return "product"
    if p.startswith("collections/"):
        return "collection"
    if p.startswith("pages/"):
        return "page"
    if p == "":
        return "home"
    return "other"


def parse(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")
    pg = Page(url=url, page_type=page_type_of(url))

    t = soup.find("title")
    pg.title = t.get_text(" ", strip=True) if t else ""
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    pg.meta_description = (md.get("content") or "").strip() if md else ""
    rb = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    pg.robots = (rb.get("content") or "").strip().lower() if rb else ""
    can = soup.find("link", rel=lambda v: v and "canonical" in v)
    pg.canonical = normalize(can.get("href"), url) if can and can.get("href") else ""

    # JSON-LD
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in (data if isinstance(data, list) else [data]):
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            for tt in (typ if isinstance(typ, list) else [typ]):
                if tt:
                    pg.schema_types.append(str(tt))
            if item.get("@type") == "FAQPage":
                for q in item.get("mainEntity", []) or []:
                    if isinstance(q, dict) and q.get("name"):
                        pg.faq_schema.append(q["name"].strip())

    # Strip chrome so headings, links and word counts reflect the page's own content
    for sel in ["header", "footer", "nav", "script", "style", "noscript", "[role=dialog]", "dialog", "aside"]:
        for el in soup.select(sel):
            el.decompose()

    main = None
    for sel in MAIN_SELECTORS:
        main = soup.select_one(sel)
        if main:
            break
    main = main or soup

    pg.h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    pg.h2s = [h.get_text(" ", strip=True) for h in main.find_all("h2")]
    pg.faq_visible = [q.get_text(" ", strip=True).rstrip("+−- ").strip() for q in soup.select(FAQ_QUESTION_SELECTOR)]

    text = main.get_text(" ", strip=True)
    pg.body_text = text
    pg.word_count = len(re.findall(r"[A-Za-z0-9'’%-]+", text))

    for a in main.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = normalize(href, url)
        item = (full, a.get_text(" ", strip=True)[:80])
        (pg.internal_links if is_internal(full) else pg.external_links).append(item)

    for img in main.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        pg.images.append((src[-120:], (img.get("alt") or "").strip()))

    # Leftover bracketed placeholders that are not a theme shortcode
    for m in re.finditer(r"\[[A-Z][^\]]{12,160}\]", text):
        if not KNOWN_SHORTCODES.match(m.group(0)):
            pg.placeholders.append(m.group(0)[:100])

    return pg
