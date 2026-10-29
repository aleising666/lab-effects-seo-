"""The nightly crawl: sitemap -> fetch each page -> parse -> check -> store."""
import sys

from sqlalchemy import insert, update

from ..config import settings
from ..db import crawl_runs, engine, findings as findings_t, now, pages as pages_t
from .checks import Finding, page_level_checks, run_checks
from .fetch import fetch, head_status, normalize, polite_sleep, should_crawl, sitemap_urls
from .parse import Page, parse


def crawl(dry_run: bool = False, limit: int | None = None, urls: list[str] | None = None) -> dict:
    urls = urls or sitemap_urls(settings.site_url)
    if not urls:
        print("No URLs found in the sitemap.", file=sys.stderr)
        return {"pages": 0, "findings": 0}
    urls = urls[: (limit or settings.crawl_max_pages)]
    print(f"Crawling {len(urls)} pages from {settings.site_url}")

    parsed: dict[str, Page] = {}
    fetched: dict[str, tuple[int, int, str]] = {}
    all_findings: list[Finding] = []

    for i, url in enumerate(urls, 1):
        f = fetch(url)
        fetched[url] = (f.status, f.redirect_hops, f.final_url)
        all_findings.extend(page_level_checks(url, f.status, f.redirect_hops, f.final_url, f.error))
        if f.status == 200 and f.html:
            parsed[url] = parse(url, f.html)
        if i % 50 == 0:
            print(f"  {i}/{len(urls)}")
        polite_sleep()

    # Status-check every internal link target we have not already fetched
    targets = set()
    for pg in parsed.values():
        for href, _ in pg.internal_links:
            if href not in fetched and should_crawl(href):
                targets.add(href)
    print(f"Checking {len(targets)} linked URLs not in the sitemap")
    for href in sorted(targets):
        fetched[href] = head_status(href)
        polite_sleep()

    for url, pg in parsed.items():
        all_findings.extend(run_checks(pg, fetched))

    if dry_run:
        _print(all_findings)
        return {"pages": len(parsed), "findings": len(all_findings)}

    with engine().begin() as conn:
        run_id = conn.execute(insert(crawl_runs).values(started_at=now())).inserted_primary_key[0]
        for url, pg in parsed.items():
            st, hops, final = fetched[url]
            conn.execute(insert(pages_t).values(
                run_id=run_id, url=url, status=st, final_url=final, redirect_hops=hops,
                title=pg.title, meta_description=pg.meta_description, h1=" | ".join(pg.h1s)[:500],
                canonical=pg.canonical, word_count=pg.word_count, internal_links=len(pg.internal_links),
                page_type=pg.page_type))
        if all_findings:
            conn.execute(insert(findings_t), [dict(run_id=run_id, url=f.url, check=f.check, severity=f.severity,
                                                   message=f.message[:2000], fingerprint=f.fingerprint)
                                              for f in all_findings])
        conn.execute(update(crawl_runs).where(crawl_runs.c.id == run_id)
                     .values(finished_at=now(), pages_crawled=len(parsed), findings_count=len(all_findings)))
    print(f"Stored run {run_id}: {len(parsed)} pages, {len(all_findings)} findings")
    return {"run_id": run_id, "pages": len(parsed), "findings": len(all_findings)}


def _print(fs: list[Finding]):
    order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(fs, key=lambda x: (order[x.severity], x.check, x.url)):
        print(f"[{f.severity:6}] {f.check:22} {f.url}\n         {f.message}")
    print(f"\n{len(fs)} findings")
