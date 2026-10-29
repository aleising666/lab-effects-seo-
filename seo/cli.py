"""python -m seo <crawl|gsc|ranks|gaps|backlinks|report|all> [options]"""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="seo")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="crawl the site and store findings")
    c.add_argument("--dry-run", action="store_true", help="print findings, store nothing")
    c.add_argument("--limit", type=int, help="only crawl the first N sitemap URLs")
    c.add_argument("--url", action="append", help="crawl only these URLs (repeatable)")

    g = sub.add_parser("gsc", help="pull Search Console data")
    g.add_argument("--days", type=int, default=3)

    sub.add_parser("ranks", help="pull every keyword we rank for (DataForSEO)")
    sub.add_parser("gaps", help="pull competitor keyword gaps (DataForSEO)")
    sub.add_parser("backlinks", help="pull backlink totals and referring domains (DataForSEO)")
    sub.add_parser("report", help="build and post the report")
    sub.add_parser("all", help="crawl, gsc, ranks, backlinks, gaps (weekly), report")

    a = p.parse_args(argv)
    if a.cmd == "crawl":
        from .crawl.run import crawl
        crawl(dry_run=a.dry_run, limit=a.limit, urls=a.url)
    elif a.cmd == "gsc":
        from .gsc.run import pull
        pull(days=a.days)
    elif a.cmd == "ranks":
        from .market.run import pull_ranks
        pull_ranks()
    elif a.cmd == "gaps":
        from .market.run import pull_gaps
        pull_gaps()
    elif a.cmd == "backlinks":
        from .market.run import pull_backlinks
        pull_backlinks()
    elif a.cmd == "report":
        report()
    elif a.cmd == "all":
        run_all()


def _try(label, fn):
    """Run one stage; a missing credential or an API hiccup skips the stage, not the report."""
    try:
        fn()
    except SystemExit as e:
        print(f"Skipping {label}: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - one bad stage must not sink the nightly report
        print(f"{label} failed: {e}", file=sys.stderr)


def run_all():
    from .config import settings
    from .crawl.run import crawl
    crawl()
    from .gsc.run import pull
    _try("Search Console", pull)
    if settings.keyword_provider != "none":
        from .db import engine
        from .market.run import gaps_are_stale, pull_backlinks, pull_gaps, pull_ranks
        _try("rank tracking", pull_ranks)
        _try("backlinks", pull_backlinks)
        with engine().begin() as conn:
            stale = gaps_are_stale(conn)
        if stale:
            _try("competitor gaps", pull_gaps)
    else:
        print("Skipping ranks/gaps/backlinks: KEYWORD_PROVIDER is none", file=sys.stderr)
    report()


def report():
    """Build the data, render the PDF, post it (with a short text summary)."""
    import os
    from .config import settings
    from .report.build import build_data, to_text
    from .report.pdf import render
    from .report.slack import post
    d = build_data()
    pdf = os.path.join(settings.report_dir, f"lab-effects-seo-report-{d['date']}.pdf")
    render(d, pdf)
    route = post(to_text(d), pdf_path=pdf, title=f"Lab Effects SEO report {d['date']}")
    print(f"Report sent via {route}: {pdf}", file=sys.stderr)


if __name__ == "__main__":
    main()
