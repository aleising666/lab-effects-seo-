"""Ahrefs API v3 provider (the account's plan includes API units).

Set KEYWORD_PROVIDER=ahrefs and AHREFS_API_KEY.

Unit budget (Lite plan: 200,000 units a month, max 100 rows per request,
every request costs at least 50 units):
  * `volume` and `keyword_difficulty` cost 10 units PER ROW each, so this
    provider never asks for them on the big nightly lists. Positions come
    back with cheap fields only; volume and difficulty go through the
    30-day keyword_volume cache (keywords-explorer/overview), so each
    keyword is priced about once a month.
  * Rough monthly spend with defaults: ranks ~15k, backlinks ~10k,
    gaps ~15k, volume cache ~20k. Check Account settings -> API usage.

Docs: https://docs.ahrefs.com/api/reference
"""
import json
import sys
from datetime import date

import requests

from ..config import settings
from .base import KeywordData, Provider

API = "https://api.ahrefs.com/v3"
PAGE = 100  # Lite plan max rows per request


class AhrefsProvider(Provider):
    name = "ahrefs"

    def __init__(self):
        if not settings.ahrefs_api_key:
            raise SystemExit("AHREFS_API_KEY is not set.")
        self.headers = {"Authorization": f"Bearer {settings.ahrefs_api_key}", "Accept": "application/json"}

    # ---- transport -------------------------------------------------------
    def _get(self, path: str, **params) -> dict:
        clean = {k: v for k, v in params.items() if v is not None}
        if "where" in clean and not isinstance(clean["where"], str):
            clean["where"] = json.dumps(clean["where"])
        r = requests.get(f"{API}{path}", headers=self.headers, params=clean, timeout=90)
        if r.status_code != 200:
            try:
                msg = r.json().get("error", r.text)
            except ValueError:
                msg = r.text
            raise RuntimeError(f"Ahrefs {path} returned {r.status_code}: {msg}")
        return r.json()

    def _pages(self, path: str, key: str, total: int, **params) -> list[dict]:
        """Page through a list endpoint 100 rows at a time until `total` or the data runs out."""
        out: list[dict] = []
        for offset in range(0, total, PAGE):
            data = self._get(path, limit=min(PAGE, total - offset), offset=offset, **params)
            rows = data.get(key) or []
            out.extend(rows)
            if len(rows) < PAGE:
                break
        return out

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    # ---- keyword volume / difficulty (cached by Provider.cached_volumes) --
    def volumes(self, keywords: list[str], country: str = "us") -> list[KeywordData]:
        out: dict[str, KeywordData] = {k: KeywordData(k) for k in keywords}
        for i in range(0, len(keywords), PAGE):
            chunk = keywords[i:i + PAGE]
            data = self._get("/keywords-explorer/overview", country=country,
                             keywords=",".join(chunk), select="keyword,volume,difficulty,cpc")
            for it in data.get("keywords") or []:
                k = it.get("keyword")
                if k in out:
                    out[k].volume = it.get("volume")
                    out[k].difficulty = it.get("difficulty")
                    cpc = it.get("cpc")
                    out[k].cpc = (cpc / 100) if isinstance(cpc, (int, float)) and cpc > 50 else cpc
        return list(out.values())

    # ---- market data -----------------------------------------------------
    def ranked_keywords(self, domain: str, country: str = "us", limit: int = 1000) -> list[dict]:
        """Every keyword `domain` ranks for (top 100), cheap fields only; volume via the cache."""
        rows = self._pages("/site-explorer/organic-keywords", "keywords", limit,
                           target=domain, country=country, date=self._today(), mode="subdomains",
                           select="keyword,best_position,best_position_url",
                           where={"field": "best_position", "is": ["lte", 100]},
                           order_by="sum_traffic:desc")
        out = [dict(keyword=r["keyword"], position=r.get("best_position"), url=r.get("best_position_url"),
                    volume=None, difficulty=None, result_type="organic") for r in rows if r.get("keyword")]
        self._attach_volumes(out, country)
        return out

    def keyword_gaps(self, competitor: str, our_domain: str, country: str = "us", limit: int = 300) -> list[dict]:
        """Keywords `competitor` ranks top-20 for that `our_domain` does not rank for at all.
        Ahrefs v3 has no gap endpoint on this plan, so: competitor's top keywords minus ours."""
        ours = {r["keyword"].lower() for r in self._pages(
            "/site-explorer/organic-keywords", "keywords", 2000,
            target=our_domain, country=country, date=self._today(), mode="subdomains",
            select="keyword", where={"field": "best_position", "is": ["lte", 100]})}
        theirs = self._pages("/site-explorer/organic-keywords", "keywords", limit * 3,
                             target=competitor, country=country, date=self._today(), mode="subdomains",
                             select="keyword,best_position,best_position_url",
                             where={"field": "best_position", "is": ["lte", 20]},
                             order_by="sum_traffic:desc")
        out = []
        for r in theirs:
            k = (r.get("keyword") or "").strip()
            if not k or k.lower() in ours:
                continue
            out.append(dict(keyword=k, volume=None, difficulty=None,
                            competitor_position=r.get("best_position"), competitor_url=r.get("best_position_url")))
            if len(out) >= limit:
                break
        self._attach_volumes(out, country)
        # Drop near-zero terms, but keep rows whose volume is simply unknown.
        return [g for g in out if g["volume"] is None or g["volume"] >= 20]

    def backlink_summary(self, domain: str) -> dict:
        stats = self._get("/site-explorer/backlinks-stats", target=domain, date=self._today(), mode="subdomains")
        m = stats.get("metrics") or stats
        dr = self._get("/site-explorer/domain-rating", target=domain, date=self._today())
        d = dr.get("domain_rating") or dr
        return dict(backlinks=m.get("live"), referring_domains=m.get("live_refdomains"),
                    referring_main_domains=None, rank=_int(d.get("domain_rating")), broken_backlinks=None)

    def referring_domains(self, domain: str, limit: int = 1000) -> list[dict]:
        rows = self._pages("/site-explorer/refdomains", "refdomains", limit,
                           target=domain, date=self._today(), mode="subdomains",
                           select="domain,domain_rating,links_to_target,first_seen",
                           order_by="domain_rating:desc")
        return [dict(domain=r.get("domain"), rank=_int(r.get("domain_rating")), backlinks=r.get("links_to_target"),
                     first_seen=(r.get("first_seen") or "")[:10]) for r in rows if r.get("domain")]

    # ---- helpers ---------------------------------------------------------
    def _attach_volumes(self, rows: list[dict], country: str) -> None:
        """Fill volume/difficulty from the 30-day cache, fetching only what is missing."""
        kws = sorted({r["keyword"] for r in rows})
        if not kws:
            return
        try:
            cache = self.cached_volumes(kws, country)
        except Exception as e:  # noqa: BLE001 - volumes are nice to have, positions are the point
            print(f"Ahrefs volume lookup skipped: {e}", file=sys.stderr)
            return
        for r in rows:
            kd = cache.get(r["keyword"])
            if kd:
                r["volume"], r["difficulty"] = kd.volume, kd.difficulty


def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None
