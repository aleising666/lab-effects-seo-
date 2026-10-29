"""Market data pulls: rank tracking, competitor keyword gaps, backlinks.

All three need KEYWORD_PROVIDER=dataforseo. Each pull stores one day's
snapshot and replaces that day if run twice, so a rerun never doubles rows.

  pull_ranks()      nightly   every keyword we rank for, with position + volume
  pull_gaps()       weekly    per competitor, keywords they rank top-20 for and we do not
  pull_backlinks()  nightly   totals + the list of referring domains (diffed in the report)

Rough cost per month with defaults: ranks ~$0.60, backlinks ~$1.50, gaps ~$0.40.
"""
import sys
from datetime import date, timedelta

from sqlalchemy import delete, func, insert, select

from ..config import settings
from ..db import backlink_snapshots, engine, keyword_gaps, rank_snapshots, referring_domains
from ..keywords.base import get_provider


def _provider():
    p = get_provider()
    if p.name == "none":
        raise SystemExit("Market data needs KEYWORD_PROVIDER=dataforseo (and its login/password).")
    return p


def _replace_day(conn, table, day, extra_where=None):
    q = delete(table).where(table.c.date == day)
    if extra_where is not None:
        q = q.where(extra_where)
    conn.execute(q)


def pull_ranks(day: date | None = None, provider=None) -> int:
    day = day or date.today()
    p = provider or _provider()
    rows = p.ranked_keywords(settings.host, settings.country, settings.rank_limit)
    with engine().begin() as conn:
        _replace_day(conn, rank_snapshots, day)
        if rows:
            conn.execute(insert(rank_snapshots), [dict(date=day, **r) for r in rows])
    print(f"Ranks: {len(rows)} keywords stored for {day}", file=sys.stderr)
    return len(rows)


def pull_gaps(day: date | None = None, provider=None, competitors=None) -> int:
    day = day or date.today()
    p = provider or _provider()
    total = 0
    with engine().begin() as conn:
        for comp in (competitors or settings.competitors):
            rows = p.keyword_gaps(comp, settings.host, settings.country, settings.gap_limit)
            _replace_day(conn, keyword_gaps, day, keyword_gaps.c.competitor == comp)
            if rows:
                conn.execute(insert(keyword_gaps), [dict(date=day, competitor=comp, **r) for r in rows])
            print(f"Gaps: {len(rows)} keywords from {comp}", file=sys.stderr)
            total += len(rows)
    return total


def pull_backlinks(day: date | None = None, provider=None) -> int:
    day = day or date.today()
    p = provider or _provider()
    summary = p.backlink_summary(settings.host)
    domains = p.referring_domains(settings.host)
    with engine().begin() as conn:
        _replace_day(conn, backlink_snapshots, day)
        conn.execute(insert(backlink_snapshots).values(date=day, **summary))
        _replace_day(conn, referring_domains, day)
        if domains:
            conn.execute(insert(referring_domains), [dict(date=day, **d) for d in domains])
    print(f"Backlinks: {summary.get('backlinks')} links from {summary.get('referring_domains')} domains", file=sys.stderr)
    return len(domains)


def gaps_are_stale(conn, days: int = 7) -> bool:
    """True when there is no gap pull in the last `days` (so `all` knows to run one)."""
    latest = conn.execute(select(func.max(keyword_gaps.c.date))).scalar()
    return latest is None or latest <= date.today() - timedelta(days=days)
