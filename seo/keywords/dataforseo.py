"""DataForSEO: pay-per-query keyword volume and difficulty.

Docs: https://docs.dataforseo.com/v3/keywords_data/google_ads/search_volume/live/
      https://docs.dataforseo.com/v3/dataforseo_labs/google/bulk_keyword_difficulty/live/
Set KEYWORD_PROVIDER=dataforseo, DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD.
"""
import requests

from ..config import settings
from .base import KeywordData, Provider

API = "https://api.dataforseo.com/v3"
LOCATION = {"us": 2840, "gb": 2826, "de": 2276, "au": 2036}


class DataForSEOProvider(Provider):
    name = "dataforseo"

    def __init__(self):
        if not (settings.dataforseo_login and settings.dataforseo_password):
            raise SystemExit("DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD are not set.")
        self.auth = (settings.dataforseo_login, settings.dataforseo_password)

    def _post(self, path: str, payload: list[dict]) -> list[dict]:
        r = requests.post(f"{API}{path}", auth=self.auth, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        if data.get("status_code") != 20000:
            raise RuntimeError(f"DataForSEO error: {data.get('status_message')}")
        results = []
        for task in data.get("tasks", []):
            for res in task.get("result") or []:
                results.extend(res.get("items") or [res])
        return results

    def volumes(self, keywords: list[str], country: str = "us") -> list[KeywordData]:
        loc = LOCATION.get(country, 2840)
        out: dict[str, KeywordData] = {k: KeywordData(k) for k in keywords}
        # volume + cpc (Google Ads data), up to 1000 keywords per call
        for i in range(0, len(keywords), 1000):
            chunk = keywords[i:i + 1000]
            for item in self._post("/keywords_data/google_ads/search_volume/live",
                                   [{"keywords": chunk, "location_code": loc, "language_code": "en"}]):
                k = item.get("keyword")
                if k in out:
                    out[k].volume = item.get("search_volume")
                    out[k].cpc = item.get("cpc")
        # difficulty (Labs data)
        for i in range(0, len(keywords), 1000):
            chunk = keywords[i:i + 1000]
            for item in self._post("/dataforseo_labs/google/bulk_keyword_difficulty/live",
                                   [{"keywords": chunk, "location_code": loc, "language_code": "en"}]):
                k = item.get("keyword")
                if k in out:
                    out[k].difficulty = item.get("keyword_difficulty")
        return list(out.values())

    # ---- Market data: rank tracking, competitor gaps, backlinks ----------
    # Each returns plain dicts so the storage layer never sees DataForSEO's shapes.

    def ranked_keywords(self, domain: str, country: str = "us", limit: int = 1000) -> list[dict]:
        """Every keyword `domain` ranks for in the top 100 (DataForSEO Labs).
        Docs: /v3/dataforseo_labs/google/ranked_keywords/live  (~$0.01 per call + per row)"""
        loc = LOCATION.get(country, 2840)
        out = []
        for offset in range(0, limit, 1000):
            items = self._post("/dataforseo_labs/google/ranked_keywords/live", [{
                "target": domain, "location_code": loc, "language_code": "en",
                "item_types": ["organic", "featured_snippet"], "ignore_synonyms": True,
                "limit": min(1000, limit - offset), "offset": offset,
                "order_by": ["keyword_data.keyword_info.search_volume,desc"],
            }])
            for it in items:
                kd, se = it.get("keyword_data") or {}, (it.get("ranked_serp_element") or {}).get("serp_item") or {}
                if not kd.get("keyword"):
                    continue
                out.append(dict(
                    keyword=kd["keyword"], position=se.get("rank_group"), url=se.get("url"),
                    volume=(kd.get("keyword_info") or {}).get("search_volume"),
                    difficulty=(kd.get("keyword_properties") or {}).get("keyword_difficulty"),
                    result_type=se.get("type"),
                ))
            if len(items) < 1000:
                break
        return out

    def keyword_gaps(self, competitor: str, our_domain: str, country: str = "us", limit: int = 300) -> list[dict]:
        """Keywords `competitor` ranks for that `our_domain` does not rank for at all.
        Docs: /v3/dataforseo_labs/google/domain_intersection/live with intersections=false"""
        loc = LOCATION.get(country, 2840)
        items = self._post("/dataforseo_labs/google/domain_intersection/live", [{
            "target1": competitor, "target2": our_domain, "location_code": loc, "language_code": "en",
            "intersections": False, "limit": min(1000, limit),
            "order_by": ["keyword_data.keyword_info.search_volume,desc"],
            # competitor must be on page 1 or 2; skip near-zero volume noise
            "filters": [["first_domain_serp_element.rank_group", "<=", 20], "and",
                        ["keyword_data.keyword_info.search_volume", ">=", 20]],
        }])
        out = []
        for it in items:
            kd, fe = it.get("keyword_data") or {}, it.get("first_domain_serp_element") or {}
            if not kd.get("keyword"):
                continue
            out.append(dict(
                keyword=kd["keyword"], volume=(kd.get("keyword_info") or {}).get("search_volume"),
                difficulty=(kd.get("keyword_properties") or {}).get("keyword_difficulty"),
                competitor_position=fe.get("rank_group"), competitor_url=fe.get("url"),
            ))
        return out

    def backlink_summary(self, domain: str) -> dict:
        """Totals. Docs: /v3/backlinks/summary/live (~$0.02 per call)"""
        res = self._post("/backlinks/summary/live", [{"target": domain, "include_subdomains": True}])
        r = res[0] if res else {}
        return dict(backlinks=r.get("backlinks"), referring_domains=r.get("referring_domains"),
                    referring_main_domains=r.get("referring_main_domains"), rank=r.get("rank"),
                    broken_backlinks=r.get("broken_backlinks"))

    def referring_domains(self, domain: str, limit: int = 1000) -> list[dict]:
        """Who links to us, strongest first. Docs: /v3/backlinks/referring_domains/live"""
        items = self._post("/backlinks/referring_domains/live", [{
            "target": domain, "include_subdomains": True, "limit": min(1000, limit),
            "order_by": ["rank,desc"], "backlinks_status_type": "live",
        }])
        return [dict(domain=it.get("domain"), rank=it.get("rank"), backlinks=it.get("backlinks"),
                     first_seen=(it.get("first_seen") or "")[:10]) for it in items if it.get("domain")]
