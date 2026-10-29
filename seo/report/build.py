"""Build the report: what is new since the last crawl, what got fixed, and
where Search Console says the easy wins are. Output is plain Markdown that
reads fine in Slack and in a terminal.
"""
from datetime import date, timedelta

from sqlalchemy import func, select

from ..config import settings
from ..db import crawl_runs, engine, findings, gsc_daily
from ..keywords.base import get_provider

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def _last_two_runs(conn):
    rows = conn.execute(select(crawl_runs).where(crawl_runs.c.finished_at.isnot(None))
                        .order_by(crawl_runs.c.id.desc()).limit(2)).all()
    return (rows[0] if rows else None), (rows[1] if len(rows) > 1 else None)


def _findings(conn, run_id):
    return conn.execute(select(findings).where(findings.c.run_id == run_id)).all()


def crawl_section(conn) -> str:
    cur, prev = _last_two_runs(conn)
    if not cur:
        return "_No crawl has run yet._"
    cur_f = _findings(conn, cur.id)
    prev_fp = {f.fingerprint for f in _findings(conn, prev.id)} if prev else set()
    cur_fp = {f.fingerprint for f in cur_f}
    new = [f for f in cur_f if f.fingerprint not in prev_fp]
    fixed = len(prev_fp - cur_fp) if prev else 0
    by_sev = {s: sum(1 for f in cur_f if f.severity == s) for s in SEV_ORDER}

    lines = [f"*Site crawl* ({cur.pages_crawled} pages, {len(cur_f)} open findings: "
             f"{by_sev['high']} high, {by_sev['medium']} medium, {by_sev['low']} low)"]
    if prev:
        lines.append(f"Since last crawl: *{len(new)} new*, *{fixed} fixed*.")
    show = sorted(new if prev else cur_f, key=lambda f: (SEV_ORDER[f.severity], f.check))
    if not show:
        lines.append("Nothing new. :white_check_mark:")
    for f in show[:25]:
        path = f.url.replace(settings.site_url, "") or "/"
        lines.append(f"• `{f.severity}` *{f.check}* <{f.url}|{path}>\n   {f.message[:220]}")
    if len(show) > 25:
        lines.append(f"…and {len(show) - 25} more.")
    return "\n".join(lines)


def gsc_section(conn, days: int = 7) -> str:
    latest = conn.execute(select(func.max(gsc_daily.c.date))).scalar()
    if not latest:
        return "_Search Console is not connected yet (set GSC_SERVICE_ACCOUNT_JSON)._"
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
    tot_clicks = sum(r.clicks for r in cur.values()); prev_clicks = sum(r.clicks for r in prev.values())
    tot_impr = sum(r.impr for r in cur.values()); prev_impr = sum(r.impr for r in prev.values())
    lines = [f"*Search Console* (last {days} days to {this_end})",
             f"Clicks {tot_clicks} ({_delta(tot_clicks, prev_clicks)}), impressions {tot_impr} ({_delta(tot_impr, prev_impr)})"]

    # Easy wins: ranking 8-20 with real impressions
    wins = [r for r in cur.values() if 8 <= r.pos <= 20 and r.impr >= 50]
    wins.sort(key=lambda r: -r.impr)
    if wins:
        lines.append("\n*Close to page one* (position 8 to 20, most impressions first):")
        kw = get_provider().cached_volumes([r.query for r in wins[:10]]) if settings.keyword_provider != "none" else {}
        for r in wins[:10]:
            vol = f", vol {kw[r.query].volume}" if r.query in kw and kw[r.query].volume else ""
            lines.append(f"• \"{r.query}\" pos {r.pos:.1f}, {r.impr} impr{vol} → {r.page.replace(settings.site_url, '')}")

    # Biggest drops
    drops = []
    for key, r in cur.items():
        p = prev.get(key)
        if p and p.impr >= 100 and r.pos - p.pos >= 3:
            drops.append((r.pos - p.pos, key, p.pos, r.pos, r.impr))
    drops.sort(reverse=True)
    if drops:
        lines.append("\n*Position drops* (3+ places on queries with 100+ impressions):")
        for d, (page, query), a, b, impr in drops[:8]:
            lines.append(f"• \"{query}\" {a:.1f} → {b:.1f} on {page.replace(settings.site_url, '')}")

    # New queries
    new_q = [r for k, r in cur.items() if k not in prev and r.impr >= 30]
    new_q.sort(key=lambda r: -r.impr)
    if new_q:
        lines.append("\n*New queries this week:* " + ", ".join(f"\"{r.query}\"" for r in new_q[:8]))
    return "\n".join(lines)


def _delta(a, b):
    if not b:
        return "n/a"
    pct = (a - b) / b * 100
    return f"{'+' if pct >= 0 else ''}{pct:.0f}% vs prior"


def build() -> str:
    with engine().begin() as conn:
        parts = [f"*Lab Effects SEO report, {date.today()}*", crawl_section(conn), gsc_section(conn)]
    return "\n\n".join(parts)
