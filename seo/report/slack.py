"""Post the report to Slack through an incoming webhook. Falls back to stdout."""
import requests

from ..config import settings

MAX = 3900  # Slack truncates long messages; split on blank lines


def post(text: str) -> bool:
    if not settings.slack_webhook_url:
        print(text)
        print("\n(SLACK_WEBHOOK_URL not set; printed instead)")
        return False
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > MAX and cur:
            chunks.append(cur); cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    for c in chunks:
        r = requests.post(settings.slack_webhook_url, json={"text": c}, timeout=30)
        r.raise_for_status()
    return True
