"""One small database. SQLite for local runs, Postgres on Render.

Tables:
  crawl_runs      one row per crawl
  pages           what each URL looked like on each crawl
  findings        one row per problem found on a page in a crawl
  gsc_daily       Search Console rows: date x page x query
  keyword_volume  cached keyword data from the provider
  rank_snapshots  every keyword the site ranks for, per day (DataForSEO Labs)
  keyword_gaps    keywords a competitor ranks for and we do not (weekly)
  backlink_snapshots  backlink totals per day
  referring_domains   the domains linking to us, per day, to diff new/lost
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String, Table,
                        Text, create_engine, Date)

from .config import settings

metadata = MetaData()

crawl_runs = Table(
    "crawl_runs", metadata,
    Column("id", Integer, primary_key=True),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("pages_crawled", Integer, default=0),
    Column("findings_count", Integer, default=0),
)

pages = Table(
    "pages", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, nullable=False, index=True),
    Column("url", String(1024), nullable=False, index=True),
    Column("status", Integer),
    Column("final_url", String(1024)),
    Column("redirect_hops", Integer, default=0),
    Column("title", Text),
    Column("meta_description", Text),
    Column("h1", Text),
    Column("canonical", String(1024)),
    Column("word_count", Integer),
    Column("internal_links", Integer),
    Column("page_type", String(32)),
)

findings = Table(
    "findings", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, nullable=False, index=True),
    Column("url", String(1024), nullable=False, index=True),
    Column("check", String(64), nullable=False),
    Column("severity", String(8), nullable=False),  # high | medium | low
    Column("message", Text, nullable=False),
    Column("fingerprint", String(256), nullable=False, index=True),
)

gsc_daily = Table(
    "gsc_daily", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", Date, nullable=False, index=True),
    Column("page", String(1024), nullable=False, index=True),
    Column("query", String(512), nullable=False),
    Column("clicks", Integer),
    Column("impressions", Integer),
    Column("ctr", Float),
    Column("position", Float),
)

keyword_volume = Table(
    "keyword_volume", metadata,
    Column("id", Integer, primary_key=True),
    Column("keyword", String(512), nullable=False, index=True),
    Column("country", String(8), nullable=False, default="us"),
    Column("volume", Integer),
    Column("difficulty", Integer),
    Column("cpc", Float),
    Column("fetched_at", DateTime, nullable=False),
    Column("provider", String(32), nullable=False),
)

rank_snapshots = Table(
    "rank_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", Date, nullable=False, index=True),
    Column("keyword", String(512), nullable=False, index=True),
    Column("position", Integer),          # rank_group: 1 = top organic result
    Column("url", String(1024)),
    Column("volume", Integer),
    Column("difficulty", Integer),
    Column("result_type", String(32)),    # organic | paid | featured_snippet ...
)

keyword_gaps = Table(
    "keyword_gaps", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", Date, nullable=False, index=True),
    Column("competitor", String(256), nullable=False, index=True),
    Column("keyword", String(512), nullable=False),
    Column("volume", Integer),
    Column("difficulty", Integer),
    Column("competitor_position", Integer),
    Column("competitor_url", String(1024)),
)

backlink_snapshots = Table(
    "backlink_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", Date, nullable=False, index=True),
    Column("backlinks", Integer),
    Column("referring_domains", Integer),
    Column("referring_main_domains", Integer),
    Column("rank", Integer),
    Column("broken_backlinks", Integer),
)

referring_domains = Table(
    "referring_domains", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", Date, nullable=False, index=True),
    Column("domain", String(256), nullable=False, index=True),
    Column("rank", Integer),
    Column("backlinks", Integer),
    Column("first_seen", String(32)),
)

_engine = None


def engine():
    global _engine
    if _engine is None:
        url = settings.database_url
        # Render hands out postgres:// ; SQLAlchemy wants postgresql://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        _engine = create_engine(url, future=True)
        metadata.create_all(_engine)
    return _engine


def now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)
