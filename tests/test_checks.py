"""Unit tests for the parser and checks, using HTML shaped like labeffects.com."""
from seo.crawl.checks import run_checks, page_level_checks
from seo.crawl.parse import parse

SITE = "https://labeffects.com"


def wrap(body, title="OG Kush Terpenes – Lab Effects Shop", desc="A fine description of the page, long enough to pass the minimum length rule.",
         canonical=None, schema=""):
    can = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return f"""<!doctype html><html><head><title>{title}</title>
    <meta name="description" content="{desc}">{can}{schema}</head>
    <body><header><a href="/collections/all">Shop</a></header>
    <main class="ar-prose">{body}</main>
    <footer><a href="/pages/contact">Contact</a></footer></body></html>"""


def checks_for(url, html, link_status=None):
    pg = parse(url, html)
    return {f.check: f for f in run_checks(pg, link_status)}


def test_double_brand_title_is_flagged():
    html = wrap("<h1>OG Kush</h1><p>" + "word " * 700 + "</p><p><a href='/collections/x'>x</a> <a href='/products/y'>y</a></p>",
                title="OG Kush Terpenes | Lab Effects – Lab Effects Shop")
    c = checks_for(f"{SITE}/blogs/news/og-kush", html)
    assert "title-double-brand" in c
    assert "title-long" not in c


def test_clean_article_has_no_findings():
    body = "<h1>OG Kush</h1><p>" + "word " * 700 + "</p><p><a href='/collections/x'>x</a> <a href='/products/y'>y</a></p>"
    c = checks_for(f"{SITE}/blogs/news/og-kush", wrap(body))
    assert c == {}, c


def test_article_with_no_links_and_british_spelling():
    body = "<h1>Top 10</h1><p>Where the flavour goes and the hash behaviour, polarising stuff. " + "word " * 700 + "</p>"
    c = checks_for(f"{SITE}/blogs/news/top-10", wrap(body))
    assert "few-internal-links" in c
    assert "british-spelling" in c
    assert "flavour" in c["british-spelling"].message


def test_placeholder_and_em_dash_and_stale_count():
    body = ("<h1>Australia</h1><p>[Looking for Premium Terpenes? Get them delivered!]</p>"
            "<p>We offer over 105 strains — and counting. " + "word " * 700 + "</p>"
            "<p><a href='/a'>a</a><a href='/b'>b</a></p>")
    c = checks_for(f"{SITE}/blogs/news/au", wrap(body))
    assert c["placeholder-text"].severity == "high"
    assert "em-dash" in c
    assert "stale-count" in c


def test_thin_collection_and_missing_meta():
    html = wrap("<h1>Aroma Boosters</h1><p>Aroma Booster</p>", title="Aroma Boosters – Lab Effects Shop", desc="")
    c = checks_for(f"{SITE}/collections/aroma-boosters", html)
    assert "meta-missing" in c
    assert "thin-content" in c
    assert "title-short" in c   # "Aroma Boosters" alone is the brand name with no keyword


def test_faq_schema_mismatch():
    schema = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage","mainEntity":['
              '{"@type":"Question","name":"What are CDTs?","acceptedAnswer":{"@type":"Answer","text":"x"}}]}</script>')
    body = ('<h1>CDT</h1><p>' + "word " * 60 + '</p>'
            '<button class="lab-col-faqitem__q">What are CDTs? +−</button>'
            '<button class="lab-col-faqitem__q">Do CDTs contain THC? +−</button>')
    c = checks_for(f"{SITE}/collections/cdt", wrap(body, title="CDT – Lab Effects Shop", schema=schema))
    assert "faq-schema-mismatch" in c
    assert "do cdts contain thc?" in c["faq-schema-mismatch"].message


def test_broken_and_redirecting_links_use_status_map():
    body = ("<h1>Kits</h1><p>" + "word " * 60 + "</p>"
            "<a href='/products/runtz-terpenes'>Runtz</a>"
            "<a href='/products/cheese-botanical-derived-strain-terpene'>Cheese</a>"
            "<a href='https://shop.labeffects.com/products/x'>old</a>")
    status = {f"{SITE}/products/runtz-terpenes": (404, 0, f"{SITE}/products/runtz-terpenes"),
              f"{SITE}/products/cheese-botanical-derived-strain-terpene": (200, 1, f"{SITE}/products/cheese-terpenes")}
    c = checks_for(f"{SITE}/collections/kits", wrap(body, title="Kits – Lab Effects Shop"), status)
    assert c["broken-link"].severity == "high"
    assert "cheese-terpenes" in c["redirect-link"].message
    assert "old-domain-link" in c


def test_all_caps_heading_and_canonical():
    body = "<h1>CBS</h1><h2>HOW TO USE CANNA-BOTANICAL STRAINS</h2><p>" + "word " * 60 + "</p>"
    c = checks_for(f"{SITE}/collections/canna-bontanical-strain-terpenes",
                   wrap(body, title="Canna-Bontanical Blends – Lab Effects Shop", canonical=f"{SITE}/collections/canna-botanical-strain-terpenes"))
    assert "heading-all-caps" in c
    assert "canonical-mismatch" in c
    assert "title-typo" in c


def test_page_level_checks():
    assert page_level_checks("u", 404, 0, "u")[0].check == "not-found"
    assert page_level_checks("u", 200, 2, "v")[0].check == "redirect-chain"
    assert page_level_checks("u", 200, 1, "v")[0].check == "sitemap-redirect"
    assert page_level_checks("u", 0, 0, "u", "timeout")[0].check == "fetch-error"
    assert page_level_checks("u", 200, 0, "u") == []


def test_parser_ignores_chrome_links_and_counts_body_links():
    body = "<h1>T</h1><p><a href='/blogs/news/other'>other</a> <a href='#top'>top</a> <a href='mailto:a@b.c'>mail</a></p>"
    pg = parse(f"{SITE}/blogs/news/t", wrap(body))
    assert [h for h, _ in pg.internal_links] == [f"{SITE}/blogs/news/other"]
    assert pg.page_type == "article"
