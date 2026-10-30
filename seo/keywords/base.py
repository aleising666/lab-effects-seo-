"""Keyword data providers.

The system runs with no paid data (NoneProvider). A rented API is a
drop-in: implement `volumes()` (plus the four market methods) and register it in
`get_provider()`. Providers: none | ahrefs (preferred, the account has API units) | dataforseo.
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import insert, select

from ..config import settings
from ..db import engine, keyword_volume, now


@dataclass
class KeywordData:
    keyword: str
    volume: int | None = None
    difficulty: int | None = None
    cpc: float | None = None


class Provider:
    name = "none"

    def volumes(self, keywords: list[str], country: str = "us") -> list[KeywordData]:
        raise NotImplementedError

    def cached_volumes(self, keywords: list[str], country: str = "us", max_age_days: int = 30) -> dict[str, KeywordData]:
        """Serve from the cache, fetch only what is missing or stale."""
        out: dict[str, KeywordData] = {}
        cutoff = now() - timedelta(days=max_age_days)
        with engine().begin() as conn:
            rows = conn.execute(select(keyword_volume).where(
                keyword_volume.c.keyword.in_(keywords), keyword_volume.c.country == country,
                keyword_volume.c.fetched_at >= cutoff)).all()
            for r in rows:
                out[r.keyword] = KeywordData(r.keyword, r.volume, r.difficulty, r.cpc)
            missing = [k for k in keywords if k not in out]
            if missing and self.name != "none":
                fresh = self.volumes(missing, country)
                for kd in fresh:
                    out[kd.keyword] = kd
                    conn.execute(insert(keyword_volume).values(
                        keyword=kd.keyword, country=country, volume=kd.volume, difficulty=kd.difficulty,
                        cpc=kd.cpc, fetched_at=now(), provider=self.name))
        return out


class NoneProvider(Provider):
    name = "none"

    def volumes(self, keywords, country="us"):
        return []


def get_provider() -> Provider:
    if settings.keyword_provider == "ahrefs":
        from .ahrefs import AhrefsProvider
        return AhrefsProvider()
    if settings.keyword_provider == "dataforseo":
        from .dataforseo import DataForSEOProvider
        return DataForSEOProvider()
    return NoneProvider()
