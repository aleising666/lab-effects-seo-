"""python -m seo <crawl|gsc|report|all> [--dry-run] [--limit N] [--url URL ...]"""
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

    sub.add_parser("report", help="build and post the report")
    sub.add_parser("all", help="crawl, gsc, report")

    a = p.parse_args(argv)
    if a.cmd == "crawl":
        from .crawl.run import crawl
        crawl(dry_run=a.dry_run, limit=a.limit, urls=a.url)
    elif a.cmd == "gsc":
        from .gsc.run import pull
        pull(days=a.days)
    elif a.cmd == "report":
        report()
    elif a.cmd == "all":
        from .crawl.run import crawl
        crawl()
        try:
            from .gsc.run import pull
            pull()
        except SystemExit as e:
            print(f"Skipping Search Console: {e}", file=sys.stderr)
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
