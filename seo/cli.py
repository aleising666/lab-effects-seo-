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
        from .report.build import build
        from .report.slack import post
        post(build())
    elif a.cmd == "all":
        from .crawl.run import crawl
        from .report.build import build
        from .report.slack import post
        crawl()
        try:
            from .gsc.run import pull
            pull()
        except SystemExit as e:
            print(f"Skipping Search Console: {e}", file=sys.stderr)
        post(build())


if __name__ == "__main__":
    main()
