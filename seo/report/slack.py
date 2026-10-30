"""Send the report to Slack.

Preferred: a bot token (SLACK_BOT_TOKEN) and channel ID (SLACK_CHANNEL_ID).
That lets us upload the PDF with a short summary as the message. The bot
needs the scopes chat:write and files:write and must be invited to the channel.

Fallback: an incoming webhook (SLACK_WEBHOOK_URL), text only, no file.
Last resort: print to stdout.
"""
import os

import requests

from ..config import settings

API = "https://slack.com/api"
MAX = 3900


def _post_api(method: str, **kwargs):
    r = requests.post(f"{API}/{method}", headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                      timeout=60, **kwargs)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {data.get('error')}")
    return data


def upload_pdf(pdf_path: str, summary: str, title: str) -> None:
    """Upload a file with Slack's two-step external upload, then share it to the channel."""
    size = os.path.getsize(pdf_path)
    filename = os.path.basename(pdf_path)
    step1 = _post_api("files.getUploadURLExternal", data={"filename": filename, "length": size})
    with open(pdf_path, "rb") as fh:
        up = requests.post(step1["upload_url"], files={"file": (filename, fh, "application/pdf")}, timeout=120)
        up.raise_for_status()
    _post_api("files.completeUploadExternal", json={
        "files": [{"id": step1["file_id"], "title": title}],
        "channel_id": settings.slack_channel_id,
        "initial_comment": summary,
    })


def post_text(text: str) -> None:
    if settings.slack_bot_token and settings.slack_channel_id:
        _post_api("chat.postMessage", json={"channel": settings.slack_channel_id, "text": text[:MAX]})
    elif settings.slack_webhook_url:
        r = requests.post(settings.slack_webhook_url, json={"text": text[:MAX]}, timeout=30)
        r.raise_for_status()
    else:
        print(text)


def post(summary: str, pdf_path: str | None = None, title: str = "SEO report") -> str:
    """Returns which route was used: bot-pdf | bot-text | webhook | stdout."""
    if settings.slack_bot_token and settings.slack_channel_id:
        if pdf_path:
            upload_pdf(pdf_path, summary, title)
            return "bot-pdf"
        post_text(summary)
        return "bot-text"
    if settings.slack_webhook_url:
        post_text(summary + ("\n(PDF attached only when SLACK_BOT_TOKEN is set)" if pdf_path else ""))
        return "webhook"
    print(summary)
    if pdf_path:
        print(f"\nPDF written to {pdf_path} (no Slack credentials set)")
    return "stdout"
