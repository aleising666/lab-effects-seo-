"""Rank tracking, competitor gaps and backlinks, with a fake provider (no API calls)."""
import os
from datetime import date, timedelta

import pytest


class FakeProvider:
    name = "fake"

    def __init__(self, ranks, gaps, summary, domains):
        self._ranks, self._gaps, self._summary, self._domains = ranks, gaps, summary, domains

    def ranked_keywords(self, domain, country="us", limit=1000):
        return self._ranks

    def keyword_gaps(self, competitor, our_domain, country="us", limit=300):
        return self._gaps.get(competitor, [])

    def backlink_summary(self, domain):
        return self._summary

    def referring_domains(self, domain, limit=1000):
        return self._domains


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import seo.config as cfg
    import seo.db as db
    monkeypatch.setattr(cfg, "settings", cfg.Settings(database_url=f"sqlite:///{tmp_path}/t.db",
                                                       keyword_provider="dataforseo",
                                                       competitors=("comp-a.com", "comp-b.com")))
    monkeypatch.setattr(db, "settings", cfg.settings)
    import seo.market.run as run
    import seo.market.report as rep
    monkeypatch.setattr(run, "settings", cfg.settings)
    db._engine = None
    yield run, rep, db
    db._engine = None


def test_rank_movers(fresh_db):
    run, rep, db = fresh_db
    week_ago, today = date.today() - timedelta(days=7), date.today()
    before = FakeProvider([
        dict(keyword="botanical terpenes", position=12, url="https://labeffects.com/collections/botanical", volume=900, difficulty=30, result_type="organic"),
        dict(keyword="terpene sample kit", position=4, url="https://labeffects.com/products/kit", volume=200, difficulty=10, result_type="organic"),
        dict(keyword="cdt terpenes", position=2, url="https://labeffects.com/collections/cdt", volume=500, difficulty=20, result_type="organic"),
    ], {}, {}, [])
    after = FakeProvider([
        dict(keyword="botanical terpenes", position=7, url="https://labeffects.com/collections/botanical", volume=900, difficulty=30, result_type="organic"),
        dict(keyword="terpene sample kit", position=14, url="https://labeffects.com/products/kit", volume=200, difficulty=10, result_type="organic"),
        dict(keyword="cdt terpenes", position=2, url="https://labeffects.com/collections/cdt", volume=500, difficulty=20, result_type="organic"),
        dict(keyword="limonene for sale", position=9, url="https://labeffects.com/products/limonene", volume=300, difficulty=15, result_type="organic"),
    ], {}, {}, [])
    assert run.pull_ranks(week_ago, before) == 3
    assert run.pull_ranks(today, after) == 4
    assert run.pull_ranks(today, after) == 4  # rerun replaces, never doubles

    with db.engine().begin() as conn:
        r = rep.rank_data(conn)
    assert r["available"] and r["baseline"] == str(week_ago)
    assert r["now"]["total"] == 4 and r["now"]["top10"] == 3
    assert [x["keyword"] for x in r["up"]] == ["botanical terpenes"]
    assert [x["keyword"] for x in r["down"]] == ["terpene sample kit"]
    assert {x["keyword"] for x in r["new_top10"]} == {"botanical terpenes", "limonene for sale"}
    assert [x["keyword"] for x in r["lost_page1"]] == ["terpene sample kit"]


def test_gaps_merge_shared(fresh_db):
    run, rep, db = fresh_db
    p = FakeProvider([], {
        "comp-a.com": [dict(keyword="terpenes for vape", volume=1000, difficulty=40, competitor_position=3, competitor_url="https://comp-a.com/x"),
                       dict(keyword="myrcene terpene", volume=400, difficulty=20, competitor_position=8, competitor_url="https://comp-a.com/y")],
        "comp-b.com": [dict(keyword="terpenes for vape", volume=1000, difficulty=40, competitor_position=6, competitor_url="https://comp-b.com/x")],
    }, {}, [])
    assert run.pull_gaps(date.today(), p) == 3
    with db.engine().begin() as conn:
        g = rep.gap_data(conn)
        assert not run.gaps_are_stale(conn)
    assert g["per_competitor"] == {"comp-a.com": 2, "comp-b.com": 1}
    assert [m["keyword"] for m in g["shared"]] == ["terpenes for vape"]
    assert len(g["shared"][0]["competitors"]) == 2
    assert g["top"][0]["keyword"] == "terpenes for vape"


def test_backlinks_new_and_lost(fresh_db):
    run, rep, db = fresh_db
    week_ago, today = date.today() - timedelta(days=7), date.today()
    before = FakeProvider([], {}, dict(backlinks=100, referring_domains=40, referring_main_domains=38, rank=120, broken_backlinks=2),
                          [dict(domain="leafly.com", rank=500, backlinks=3, first_seen="2025-01-01"),
                           dict(domain="old-blog.net", rank=50, backlinks=1, first_seen="2024-06-01")])
    after = FakeProvider([], {}, dict(backlinks=110, referring_domains=41, referring_main_domains=39, rank=125, broken_backlinks=2),
                         [dict(domain="leafly.com", rank=500, backlinks=3, first_seen="2025-01-01"),
                          dict(domain="future4200.com", rank=300, backlinks=4, first_seen="2026-10-25")])
    run.pull_backlinks(week_ago, before)
    run.pull_backlinks(today, after)
    with db.engine().begin() as conn:
        b = rep.backlink_data(conn)
    assert b["backlinks_delta"] == 10 and b["domains_delta"] == 1
    assert [x["domain"] for x in b["new"]] == ["future4200.com"]
    assert [x["domain"] for x in b["lost"]] == ["old-blog.net"]


def test_pdf_renders_market_pages(fresh_db, tmp_path):
    run, rep, db = fresh_db
    from seo.report.build import build_data, to_text
    from seo.report.pdf import render
    p = FakeProvider([dict(keyword="terpenes", position=5, url="https://labeffects.com/", volume=5000, difficulty=60, result_type="organic")],
                     {"comp-a.com": [dict(keyword="x", volume=10, difficulty=1, competitor_position=1, competitor_url="u")]},
                     dict(backlinks=1, referring_domains=1, referring_main_domains=1, rank=1, broken_backlinks=0),
                     [dict(domain="a.com", rank=1, backlinks=1, first_seen="2026-01-01")])
    run.pull_ranks(provider=p); run.pull_gaps(provider=p); run.pull_backlinks(provider=p)
    d = build_data()
    txt = to_text(d)
    assert "Rankings: 1 keywords" in txt and "Competitor gaps" in txt and "Backlinks: 1 links" in txt
    out = render(d, str(tmp_path / "r.pdf"))
    assert os.path.getsize(out) > 5000
