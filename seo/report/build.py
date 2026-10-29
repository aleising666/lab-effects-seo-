"""Build the report as data, then render it (PDF for Slack, text as fallback).

Report structure:
  {
    "date": "2026-10-29",
    "crawl":  {"pages": int, "open": {"high": n, "medium": n, "low": n},
               "new": int|None, "fixed": int|None,
               "items": [ {severity, check, url, message} ... ]   # new since last run, or all on first run
               "grouped_low": [ {check, count, urls[], example} ... ] },
    "gsc":    {"available": bool, "window": str, "clicks": int, "clicks_delta": str,
               "impressions": int, "impr_delta": str,
               "wins": [...], "drops": [...], "new_queries": [...]},
  }
"""
from datetime import date, timedelta

from sqlalchemy import func, select

from ..config import settings
from ..db import crawl_runs, engine, findings, gsc_daily
from ..keywords.base import get_provider

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def path_of(url: str) -> str:
    return url.replace(settings.site_url, "") or "/"


def _last_two_runs(conn):
    rows = conn.execute(select(crawl_runs).where(crawl_runs.c.finished_at.isnot(None))
                        .order_by(crawl_runs.c.id.desc()).limit(2)).all()
    return (rows[0] if rows else None), (rows[1] if len(rows) > 1 else None)


def _findings(conn, run_id):
    return conn.execute(select(findings).where(findings.c.run_id == run_id)).all()


def crawl_data(conn) -> dict | None:
    cur, prev = _last_two_runs(conn)
    if not cur:
        return None
    cur_f = _findings(conn, cur.id)
    prev_fp = {f.fingerprint for f in _findings(conn, prev.id)} if prev else set()
    cur_fp = {f.fingerprint for f in cur_f}
    new = [f for f in cur_f if f.fingerprint not in prev_fp]
    show = sorted(new if prev else cur_f, key=lambda f: (SEV_ORDER[f.severity], f.check, f.url))

    items = [dict(severity=f.severity, check=f.check, url=f.url, message=f.message)
             for f in show if f.severity != "low"]
    grouped: dict[str, list] = {}
    for f in show:
        if f.severity == "low":
            grouped.setdefault(f.check, []).append(f)
    grouped_low = [dict(check=c, count=len(fs), urls=[f.url for f in fs[:5]], example=fs[0].message)
                   for c, fs in sorted(grouped.items(), key=lambda kv: -len(kv[1]))]
    return dict(
        pages=cur.pages_crawled, finished=str(cur.finished_at)[:16],
        open={s: sum(1 for f in cur_f if f.severity == s) for s in SEV_ORDER},
        new=len(new) if prev else None, fixed=len(prev_fp - cur_fp) if prev else None,
        first_run=prev is None, items=items, grouped_low=grouped_low,
        all_open=sorted(cur_f, key=lambda f: (SEV_ORDER[f.severity], f.check, f.url)),
    )


def gsc_data(conn, days: int = 7) -> dict:
    latest = conn.execute(select(func.max(gsc_daily.c.date))).scalar()
    if not latest:
        return {"available": False}
    this_end, this_start = latest, latest - timedelta(days=days - 1)
    prev_end, prev_start = this_start - timedelta(days=1), this_start - timedelta(days=days)

    def window(a, b):
        q = (select(gsc_daily.c.page, gsc_daily.c.query,
                    func.sum(gsc_daily.c.clicks).label("clicks"),
                    func.sum(gsc_daily.c.impressions).label("impr"),
                    func.avg(gsc_daily.c.position).label("pos"))
             .where(gsc_daily.c.date.between(a, b)).group_by(gsc_daily.c.page, gsc_daily.c.query))
        return {(r.page, r.query): r for r in conn.execute(q)}

    cur, prev = window(this_start, this_end), window(prev_start, prev_end)
    tc, pc = sum(r.clicks for r in cur.values()), sum(r.clicks for r in prev.values())
    ti, pi = sum(r.impr for r in cur.values()), sum(r.impr for r in prev.values())

    wins = sorted([r for r in cur.values() if 8 <= r.pos <= 20 and r.impr >= 50], key=lambda r: -r.impr)[:12]
    kw = {}
    if wins and settings.keyword_provider != "none":
        kw = get_provider().cached_volumes([r.query for r in wins])
    drops = []
    for key, r in cur.items():
        p = prev.get(key)
        if p and p.impr >= 100 and r.pos - p.pos >= 3:
            drops.append(dict(query=key[1], page=key[0], before=round(p.pos, 1), after=round(r.pos, 1), impressions=r.impr))
    drops.sort(key=lambda d: -(d["after"] - d["before"]))
    new_q = sorted([r for k, r in cur.items() if k not in prev and r.impr >= 30], key=lambda r: -r.impr)

    return dict(
        available=True, window=f"{this_start} to {this_end}",
        clicks=tc, clicks_delta=_delta(tc, pc), impressions=ti, impr_delta=_delta(ti, pi),
        wins=[dict(query=r.query, page=r.page, position=round(r.pos, 1), impressions=r.impr,
                   volume=(kw[r.query].volume if r.query in kw else None)) for r in wins],
        drops=drops[:10],
        new_queries=[dict(query=r.query, page=r.page, impressions=r.impr) for r in new_q[:10]],
    )


def _delta(a, b):
    if not b:
        return "n/a"
    pct = (a - b) / b * 100
    return f"{'+' if pct >= 0 else ''}{pct:.0f}% vs prior period"


def build_data() -> dict:
    with engine().begin() as conn:
        return dict(date=str(date.today()), site=settings.site_url, crawl=crawl_data(conn), gsc=gsc_data(conn))


def to_text(d: dict) -> str:
    """Short Slack-friendly summary (the PDF carries the detail)."""
    lines = [f"*Lab Effects SEO report, {d['date']}*"]
    c = d["crawl"]
    if not c:
        lines.append("No crawl has run yet.")
    else:
        o = c["open"]
        lines.append(f"Crawl: {c['pages']} pages, {sum(o.values())} open findings "
                     f"({o['high']} high, {o['medium']} medium, {o['low']} low).")
        if c["new"] is not None:
            lines.append(f"Since last run: {c['new']} new, {c['fixed']} fixed.")
        for it in c["items"][:5]:
            lines.append(f"• `{it['severity']}` {it['check']} on {path_of(it['url'])}")
        if len(c["items"]) > 5:
            lines.append(f"…{len(c['items']) - 5} more in the PDF.")
    g = d["gsc"]
    if g.get("available"):
        lines.append(f"Search Console ({g['window']}): {g['clicks']} clicks ({g['clicks_delta']}), "
                     f"{g['impressions']} impressions ({g['impr_delta']}). "
                     f"{len(g['wins'])} queries close to page one, {len(g['drops'])} drops.")
    else:
        lines.append("Search Console: not connected yet.")
    return "\n".join(lines)


def build() -> str:
    return to_text(build_data())
