"""Pull Google Search Console data: date x page x query.

Search Console data lags about 2 days, so each run asks for the last few days
and replaces whatever it already has for those dates (safe to re-run).
"""
import json
import sys
from datetime import date, timedelta

from sqlalchemy import delete, insert

from ..config import settings
from ..db import engine, gsc_daily

ROW_LIMIT = 25000


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if not settings.gsc_service_account_json:
        raise SystemExit("GSC_SERVICE_ACCOUNT_JSON is not set. See README step 4.")
    info = json.loads(settings.gsc_service_account_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def pull(days: int = 3, end: date | None = None) -> int:
    svc = _service()
    end = end or (date.today() - timedelta(days=2))
    start = end - timedelta(days=days - 1)
    total = 0
    with engine().begin() as conn:
        for d in (start + timedelta(n) for n in range(days)):
            rows, start_row = [], 0
            while True:
                body = {
                    "startDate": d.isoformat(), "endDate": d.isoformat(),
                    "dimensions": ["page", "query"],
                    "rowLimit": ROW_LIMIT, "startRow": start_row,
                }
                resp = svc.searchanalytics().query(siteUrl=settings.gsc_property, body=body).execute()
                batch = resp.get("rows", [])
                rows.extend(batch)
                if len(batch) < ROW_LIMIT:
                    break
                start_row += ROW_LIMIT
            conn.execute(delete(gsc_daily).where(gsc_daily.c.date == d))
            if rows:
                conn.execute(insert(gsc_daily), [
                    dict(date=d, page=r["keys"][0][:1024], query=r["keys"][1][:512],
                         clicks=int(r.get("clicks", 0)), impressions=int(r.get("impressions", 0)),
                         ctr=float(r.get("ctr", 0)), position=float(r.get("position", 0)))
                    for r in rows])
            total += len(rows)
            print(f"  {d}: {len(rows)} rows")
    print(f"Stored {total} Search Console rows for {start} to {end}", file=sys.stderr)
    return total
