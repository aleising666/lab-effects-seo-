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
