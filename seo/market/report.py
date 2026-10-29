"""Turn the stored market snapshots into report sections.

rank_data():     latest snapshot vs the one closest to 7 days earlier
                 -> movers up/down (3+ places), new top-10, dropped off page 1, totals
gap_data():      latest gap pull per competitor, merged and ranked by volume
backlink_data(): totals vs previous, plus referring domains that appeared / disappeared
"""
from datetime import date, timedelta

from sqlalchemy import func, select

from ..db import backlink_snapshots, keyword_gaps, rank_snapshots, referring_domains

MOVE = 3  # positions a keyword must move to count


def _dates(conn, table):
    return sorted(r[0] for r in conn.execute(select(table.c.date).distinct()))


def _baseline(dates: list, latest: date, back_days: int = 7):
    """The snapshot date closest to `back_days` before `latest`, or the previous one."""
    earlier = [d for d in dates if d < latest]
    if not earlier:
        return None
    target = latest - timedelta(days=back_days)
    return min(earlier, key=lambda d: abs((d - target).days))


def rank_data(conn) -> dict:
    dates = _dates(conn, rank_snapshots)
    if not dates:
        return {"available": False}
    latest = dates[-1]
    base = _baseline(dates, latest)

    def snap(day):
        rows = conn.execute(select(rank_snapshots).where(rank_snapshots.c.date == day)).all()
        return {r.keyword: r for r in rows if r.position}

    cur = snap(latest)
    prev = snap(base) if base else {}

    def buckets(s):
        return dict(total=len(s), top3=sum(1 for r in s.values() if r.position <= 3),
                    top10=sum(1 for r in s.values() if r.position <= 10),
                    top20=sum(1 for r in s.values() if r.position <= 20))

    up, down, new_top10, lost_page1 = [], [], [], []
    for k, r in cur.items():
        p = prev.get(k)
        row = dict(keyword=k, position=r.position, url=r.url, volume=r.volume or 0,
                   before=p.position if p else None)
        if p:
            if p.position - r.position >= MOVE:
                up.append(row)
            elif r.position - p.position >= MOVE:
                down.append(row)
            if r.position <= 10 < p.position:
                new_top10.append(row)
        elif prev and r.position <= 10:
            new_top10.append(row)
    for k, p in prev.items():
        r = cur.get(k)
        if p.position <= 10 and (r is None or r.position > 10):
            lost_page1.append(dict(keyword=k, before=p.position, position=r.position if r else None,
                                   url=p.url, volume=p.volume or 0))

    by_vol = lambda rows: sorted(rows, key=lambda x: (-(x["volume"] or 0), x["position"] or 999))
    return dict(
        available=True, date=str(latest), baseline=str(base) if base else None,
        now=buckets(cur), before=buckets(prev) if prev else None,
        up=by_vol(up)[:15], down=by_vol(down)[:15],
        new_top10=by_vol(new_top10)[:15], lost_page1=by_vol(lost_page1)[:15],
        top=sorted(cur.values(), key=lambda r: (-(r.volume or 0), r.position))[:20],
    )


def gap_data(conn) -> dict:
    latest = conn.execute(select(func.max(keyword_gaps.c.date))).scalar()
    if not latest:
        return {"available": False}
    rows = conn.execute(select(keyword_gaps).where(keyword_gaps.c.date == latest)).all()
    merged: dict[str, dict] = {}
    for r in rows:
        m = merged.setdefault(r.keyword, dict(keyword=r.keyword, volume=r.volume or 0,
                                              difficulty=r.difficulty, competitors=[]))
        m["competitors"].append(dict(domain=r.competitor, position=r.competitor_position, url=r.competitor_url))
    items = sorted(merged.values(), key=lambda m: (-len(m["competitors"]), -m["volume"]))
    per_comp = {}
    for r in rows:
        per_comp[r.competitor] = per_comp.get(r.competitor, 0) + 1
    return dict(available=True, date=str(latest), per_competitor=per_comp,
                shared=[m for m in items if len(m["competitors"]) >= 2][:15],
                top=sorted(merged.values(), key=lambda m: -m["volume"])[:25])


def backlink_data(conn) -> dict:
    dates = _dates(conn, backlink_snapshots)
    if not dates:
        return {"available": False}
    latest = dates[-1]
    base = _baseline(dates, latest)
    cur = conn.execute(select(backlink_snapshots).where(backlink_snapshots.c.date == latest)).first()
    prev = conn.execute(select(backlink_snapshots).where(backlink_snapshots.c.date == base)).first() if base else None

    def doms(day):
        return {r.domain: r for r in conn.execute(select(referring_domains).where(referring_domains.c.date == day))}

    cd = doms(latest)
    pd = doms(base) if base else {}
    new = sorted([cd[d] for d in cd.keys() - pd.keys()], key=lambda r: -(r.rank or 0)) if pd else []
    lost = sorted([pd[d] for d in pd.keys() - cd.keys()], key=lambda r: -(r.rank or 0)) if pd else []
    row = lambda r: dict(domain=r.domain, rank=r.rank, backlinks=r.backlinks, first_seen=r.first_seen)
    return dict(
        available=True, date=str(latest), baseline=str(base) if base else None,
        backlinks=cur.backlinks, referring_domains=cur.referring_domains, rank=cur.rank,
        broken=cur.broken_backlinks,
        backlinks_delta=(cur.backlinks or 0) - (prev.backlinks or 0) if prev else None,
        domains_delta=(cur.referring_domains or 0) - (prev.referring_domains or 0) if prev else None,
        new=[row(r) for r in new[:15]], lost=[row(r) for r in lost[:15]],
        top=[row(r) for r in sorted(cd.values(), key=lambda r: -(r.rank or 0))[:15]],
    )
