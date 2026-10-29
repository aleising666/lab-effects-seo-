"""The rules. Each check returns zero or more Findings for one page.

Every rule here comes from a real problem found on labeffects.com in
October 2026 (the outside SEO audit and the blog audit), so the list is
what has actually gone wrong, not a generic checklist.
"""
import hashlib
import re
from dataclasses import dataclass

from .parse import Page, BRAND_SUFFIX

HIGH, MEDIUM, LOW = "high", "medium", "low"

# House style: American English only, no em dashes.
BRITISH = re.compile(
    r"\b(flavour\w*|colour\w*|odour\w*|vapour\w*|behaviour\w*|analys(e|ed|es|ing)|characteris(e|ed|es|ing)|"
    r"organis(e|ed|es|ing)|optimis(e|ed|es|ing)|polaris(e|ed|es|ing)|labelled|cancelled|centre|litre\w*|"
    r"programme|grey|whilst|amongst|savoury|favourite|catalogue)\b", re.I)

TITLE_MAX = 60       # characters before the theme adds the brand suffix
TITLE_MIN = 15
DESC_MAX = 160
DESC_MIN = 70
THIN_WORDS = {"article": 600, "collection": 40, "product": 60, "page": 100}
MIN_BODY_LINKS = {"article": 2}


@dataclass
class Finding:
    url: str
    check: str
    severity: str
    message: str

    @property
    def fingerprint(self) -> str:
        raw = f"{self.url}|{self.check}|{self.message[:120]}"
        return hashlib.sha1(raw.encode()).hexdigest()


def run_checks(pg: Page, link_status: dict[str, tuple[int, int, str]] | None = None) -> list[Finding]:
    """link_status maps internal URL -> (status, redirect_hops, final_url), filled after the crawl."""
    out: list[Finding] = []
    F = lambda check, sev, msg: out.append(Finding(pg.url, check, sev, msg))
    bare_title = pg.title[:-len(BRAND_SUFFIX)] if pg.title.endswith(BRAND_SUFFIX) else pg.title

    # --- Indexability ---
    if "noindex" in pg.robots:
        F("noindex", HIGH, "Page is set to noindex")
    if pg.canonical and pg.canonical != pg.url:
        F("canonical-mismatch", MEDIUM, f"Canonical points elsewhere: {pg.canonical}")

    # --- Title tag ---
    if not pg.title:
        F("title-missing", HIGH, "No <title>")
    else:
        if "Lab Effects" in bare_title:
            F("title-double-brand", MEDIUM,
              f"Title already says 'Lab Effects' and the theme adds '{BRAND_SUFFIX.strip()}' again: '{pg.title}'")
        if len(bare_title) > TITLE_MAX:
            F("title-long", LOW, f"Title is {len(bare_title)} characters before the brand suffix (aim under {TITLE_MAX}): '{bare_title}'")
        elif len(bare_title) < TITLE_MIN:
            F("title-short", LOW, f"Title is only {len(bare_title)} characters: '{bare_title}'")
        if pg.page_type == "collection" and re.search(r"\b(bontanical|terpens|terpenese)\b", bare_title, re.I):
            F("title-typo", HIGH, f"Likely typo in title: '{bare_title}'")

    # --- Meta description ---
    if not pg.meta_description:
        F("meta-missing", MEDIUM, "No meta description")
    elif len(pg.meta_description) > DESC_MAX:
        F("meta-long", LOW, f"Meta description is {len(pg.meta_description)} characters (Google cuts at about {DESC_MAX})")
    elif len(pg.meta_description) < DESC_MIN:
        F("meta-short", LOW, f"Meta description is only {len(pg.meta_description)} characters: '{pg.meta_description}'")

    # --- Headings ---
    if len(pg.h1s) == 0:
        F("h1-missing", MEDIUM, "No H1 on the page")
    elif len(pg.h1s) > 1:
        F("h1-multiple", LOW, f"{len(pg.h1s)} H1s: {pg.h1s[:3]}")
    caps = [h for h in pg.h2s if len(h) > 12 and h == h.upper()]
    if caps:
        F("heading-all-caps", LOW, f"{len(caps)} heading(s) typed in ALL CAPS (use sentence case + CSS): {caps[:2]}")

    # --- Content ---
    limit = THIN_WORDS.get(pg.page_type)
    if limit and pg.word_count < limit:
        F("thin-content", MEDIUM if pg.page_type == "article" else LOW,
          f"Only {pg.word_count} words of visible copy (expect at least {limit} for a {pg.page_type})")
    if pg.page_type == "article" and len(pg.internal_links) < MIN_BODY_LINKS["article"]:
        F("few-internal-links", MEDIUM, f"Only {len(pg.internal_links)} internal link(s) in the body; add links to collections, products or related posts")
    if "—" in pg.body_text or "—" in pg.title or "—" in pg.meta_description:
        F("em-dash", LOW, "Em dash in copy (house style: use a comma)")
    hits = sorted(set(m.group(0).lower() for m in BRITISH.finditer(pg.body_text)))
    if hits:
        F("british-spelling", LOW, f"British spelling in copy: {hits[:6]}")
    for ph in pg.placeholders[:5]:
        F("placeholder-text", HIGH, f"Bracketed placeholder printing on the page: {ph}")
    if re.search(r"\bover (50|55|105)\b|\b(40|100)\+ ", pg.body_text):
        F("stale-count", LOW, "Copy carries an old strain count ('over 50/55/105', '40+', '100+'); the catalog lists 130+")

    # --- Images ---
    noalt = [s for s, a in pg.images if not a]
    if noalt:
        F("img-no-alt", LOW, f"{len(noalt)} image(s) without alt text, e.g. {noalt[0]}")

    # --- FAQ schema vs visible FAQ ---
    if pg.faq_schema or pg.faq_visible:
        vis = set(q.lower() for q in pg.faq_visible)
        sch = set(q.lower() for q in pg.faq_schema)
        if pg.page_type == "product" and pg.faq_schema:
            F("faq-schema-on-product", MEDIUM, "FAQPage schema on a product page (should live only on the collection)")
        elif pg.faq_visible and not pg.faq_schema and pg.page_type == "collection":
            F("faq-schema-missing", LOW, f"{len(pg.faq_visible)} visible FAQs but no FAQPage schema")
        elif vis and sch and vis != sch:
            F("faq-schema-mismatch", MEDIUM,
              f"FAQ schema ({len(sch)}) does not match visible FAQ ({len(vis)}); missing from schema: {sorted(vis - sch)[:3]}")

    # --- Links (needs the post-crawl status map) ---
    if link_status:
        broken, redirecting, old_shop = [], [], []
        for href, _ in pg.internal_links:
            st = link_status.get(href)
            if not st:
                continue
            status, hops, final = st
            if status == 404 or status == 410:
                broken.append(href)
            elif hops > 0 and final != href:
                redirecting.append(f"{href} -> {final}")
        for href, _ in pg.external_links:
            if "myshopify.com" in href or "shop.labeffects.com" in href:
                old_shop.append(href)
        if broken:
            F("broken-link", HIGH, f"{len(broken)} internal link(s) 404: {broken[:3]}")
        if redirecting:
            F("redirect-link", MEDIUM, f"{len(redirecting)} internal link(s) go through a redirect: {redirecting[:3]}")
        if old_shop:
            F("old-domain-link", MEDIUM, f"{len(old_shop)} link(s) to the old shop domain: {old_shop[:3]}")

    return out


def page_level_checks(url: str, status: int, hops: int, final_url: str, error: str = "") -> list[Finding]:
    """Checks on the fetch itself, before parsing."""
    out = []
    if error:
        out.append(Finding(url, "fetch-error", HIGH, f"Could not fetch: {error}"))
    elif status >= 500:
        out.append(Finding(url, "server-error", HIGH, f"HTTP {status}"))
    elif status == 404:
        out.append(Finding(url, "not-found", HIGH, "Sitemap URL returns 404"))
    elif hops > 1:
        out.append(Finding(url, "redirect-chain", MEDIUM, f"{hops} redirects before landing on {final_url}"))
    elif hops == 1 and final_url != url:
        out.append(Finding(url, "sitemap-redirect", LOW, f"Sitemap URL redirects to {final_url}"))
    return out
