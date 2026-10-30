"""Ahrefs provider: request shaping, paging and response parsing, with HTTP mocked."""
import json

import pytest


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, json.dumps(payload)

    def json(self):
        return self._p


@pytest.fixture
def provider(monkeypatch, tmp_path):
    import seo.config as cfg
    import seo.db as db
    monkeypatch.setattr(cfg, "settings", cfg.Settings(database_url=f"sqlite:///{tmp_path}/t.db",
                                                       keyword_provider="ahrefs", ahrefs_api_key="k"))
    monkeypatch.setattr(db, "settings", cfg.settings)
    db._engine = None
    import seo.keywords.ahrefs as ah
    import seo.keywords.base as base
    monkeypatch.setattr(ah, "settings", cfg.settings)
    monkeypatch.setattr(base, "settings", cfg.settings)
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url.split("/v3")[1], params))
        if url.endswith("/site-explorer/organic-keywords"):
            offset = int(params.get("offset", 0))
            n = 100 if offset == 0 else 20  # 120 rows total
            if params.get("target") == "comp.com":
                rows = [{"keyword": f"comp kw {i}", "best_position": 3, "best_position_url": "https://comp.com/p"} for i in range(offset, offset + n)]
                rows[0]["keyword"] = "shared kw"  # we rank for this one
            else:
                rows = [{"keyword": f"kw {i}", "best_position": (i % 30) + 1, "best_position_url": f"https://labeffects.com/p{i}"} for i in range(offset, offset + n)]
                rows[0]["keyword"] = "shared kw"
            return FakeResp({"keywords": rows})
        if url.endswith("/keywords-explorer/overview"):
            kws = params["keywords"].split(",")
            return FakeResp({"keywords": [{"keyword": k, "volume": 500, "difficulty": 12, "cpc": 150} for k in kws]})
        if url.endswith("/site-explorer/backlinks-stats"):
            return FakeResp({"metrics": {"live": 2100, "all_time": 5000, "live_refdomains": 540, "all_time_refdomains": 900}})
        if url.endswith("/site-explorer/domain-rating"):
            return FakeResp({"domain_rating": {"domain_rating": 38.4, "ahrefs_rank": 123456}})
        if url.endswith("/site-explorer/refdomains"):
            return FakeResp({"refdomains": [{"domain": "leafly.com", "domain_rating": 91, "links_to_target": 3, "first_seen": "2025-01-01T00:00:00Z"}]})
        return FakeResp({"error": "no such endpoint"}, 404)

    monkeypatch.setattr(ah.requests, "get", fake_get)
    yield ah.AhrefsProvider(), calls
    db._engine = None


def test_ranked_keywords_pages_and_prices(provider):
    p, calls = provider
    rows = p.ranked_keywords("labeffects.com", "us", 1000)
    assert len(rows) == 120 and rows[0]["position"] == 1
    assert all(r["volume"] == 500 and r["difficulty"] == 12 for r in rows)
    organic = [c for c in calls if c[0] == "/site-explorer/organic-keywords"]
    assert len(organic) == 2 and organic[1][1]["offset"] == 100 and organic[0][1]["limit"] == 100
    assert "volume" not in organic[0][1]["select"]  # expensive fields never on the nightly list
    assert json.loads(organic[0][1]["where"]) == {"field": "best_position", "is": ["lte", 100]}
    overview = [c for c in calls if c[0] == "/keywords-explorer/overview"]
    assert len(overview) == 2  # 120 keywords, 100 per call
    # second run: all volumes served from cache, no overview calls
    calls.clear()
    p.ranked_keywords("labeffects.com", "us", 1000)
    assert not [c for c in calls if c[0] == "/keywords-explorer/overview"]


def test_keyword_gaps_subtracts_ours(provider):
    p, _ = provider
    gaps = p.keyword_gaps("comp.com", "labeffects.com", "us", 300)
    assert "shared kw" not in {g["keyword"] for g in gaps}
    assert gaps and gaps[0]["competitor_position"] == 3 and gaps[0]["volume"] == 500


def test_backlinks(provider):
    p, _ = provider
    s = p.backlink_summary("labeffects.com")
    assert s == dict(backlinks=2100, referring_domains=540, referring_main_domains=None, rank=38, broken_backlinks=None)
    d = p.referring_domains("labeffects.com")
    assert d == [dict(domain="leafly.com", rank=91, backlinks=3, first_seen="2025-01-01")]


def test_api_error_is_readable(provider, monkeypatch):
    p, _ = provider
    import seo.keywords.ahrefs as ah
    monkeypatch.setattr(ah.requests, "get", lambda *a, **k: FakeResp({"error": "insufficient units"}, 403))
    with pytest.raises(RuntimeError, match="403: insufficient units"):
        p.backlink_summary("labeffects.com")
